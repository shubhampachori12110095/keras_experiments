#!/usr/bin/env python
'''Train a simple deep CNN on the CIFAR10 small images dataset.

GPU run command with Theano backend (with TensorFlow, the GPU is automatically
used):
    THEANO_FLAGS=mode=FAST_RUN,device=gpu,floatx=float32 python cifar10_cnn.py

It gets down to 0.65 test logloss in 25 epochs, and down to 0.55 after 50
epochs. (it's still underfitting at that point, though).
'''

from __future__ import print_function
import sys
import os

from argparse import SUPPRESS
from parser_common import parser_def_mgpu

from keras.utils import to_categorical
from keras.datasets import cifar10
from keras.preprocessing.image import ImageDataGenerator
from keras.models import Sequential
from keras.layers import Dense, Dropout, Activation, Flatten
from keras.layers import Conv2D, MaxPooling2D

from keras.callbacks import ModelCheckpoint

from keras_exp.multigpu import (get_available_gpus, print_mgpu_modelsummary)
from keras_exp.multigpu import make_parallel
# from keras_exp.multigpu import ModelMGPU
from keras.optimizers import RMSprop
from keras_exp.multigpu.optimizers import RMSPropMGPU


def parser_(desc):
    parser = parser_def_mgpu(desc)

    checkptfile = 'cifar10_cnn_mgpu.weights.best.hdf5'
    parser.add_argument(
        '--checkpt', action='store', nargs='?',
        const=checkptfile, default=SUPPRESS,
        help='S|Save (overwrites) and load the model weights if available.'
        '\nOptionally specify a file/filepath if the default name is '
        'undesired.\n(default: {})'.format(checkptfile))

    parser.add_argument('--aug', action='store_true', default=False,
                        help='S|Perform data augmentation on cifar10 set.\n')

    args = parser.parse_args()

    return args


def make_model(inshape, num_classes, weights_file=None):
    model = Sequential()

    model.add(Conv2D(32, (3, 3), padding='same', input_shape=inshape[1:]))
    model.add(Activation('relu'))
    model.add(Conv2D(32, (3, 3)))
    model.add(Activation('relu'))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Dropout(0.25))

    model.add(Conv2D(64, (3, 3), padding='same'))
    model.add(Activation('relu'))
    model.add(Conv2D(64, (3, 3)))
    model.add(Activation('relu'))
    model.add(MaxPooling2D(pool_size=(2, 2)))
    model.add(Dropout(0.25))

    model.add(Flatten())
    model.add(Dense(512))
    model.add(Activation('relu'))
    model.add(Dropout(0.5))
    model.add(Dense(num_classes))
    model.add(Activation('softmax'))

    if weights_file is not None and os.path.exists(weights_file):
        model.load_weights(weights_file)

    return model


def main(argv=None):
    '''
    '''
    main.__doc__ = __doc__
    argv = sys.argv if argv is None else sys.argv.extend(argv)
    desc = main.__doc__  # .format(os.path.basename(__file__))
    # CLI parser
    args = parser_(desc)
    mgpu = 0 if getattr(args, 'mgpu', None) is None else args.mgpu

    checkpt = getattr(args, 'checkpt', None)
    checkpt_flag = False if checkpt is None else True
    filepath = checkpt
    # print('CHECKPT:', checkpt)

    batch_size = 32
    num_classes = 10
    epochs = args.epochs
    data_augmentation = args.aug

    # The data, shuffled and split between train and test sets:
    (x_train, y_train), (x_test, y_test) = cifar10.load_data()
    print(x_train.shape[0], 'train samples')
    print(x_test.shape[0], 'test samples')

    # Convert class vectors to binary class matrices.
    y_train = to_categorical(y_train, num_classes)
    y_test = to_categorical(y_test, num_classes)

    callbacks = None
    model_init = make_model(x_train.shape, num_classes,
                            filepath if checkpt_flag else None)

    if checkpt_flag:
        checkpoint = ModelCheckpoint(filepath, monitor='val_acc', verbose=1,
                                     save_best_only=True, mode='max')
        callbacks = [checkpoint]

    if mgpu > 1 or mgpu == -1:
        gpus_list = get_available_gpus(mgpu)
        ngpus = len(gpus_list)
        print('Using GPUs: {}'.format(', '.join(gpus_list)))
        batch_size = batch_size * ngpus
        # partype = 'tp'  # Tower parallelization.
        partype = 'dp'  # Data parallelization.

        # Data-Parallelize the model via function or class.
        model = make_parallel(model_init, gpus_list, partype=partype)
        # model = ModelMGPU(serial_model=model_init, gdev_list=gpus_list,
        #                   partype=partype)
        print_mgpu_modelsummary(model)
        opt = RMSprop(lr=0.0001, decay=1e-6)
        # opt = RMSPropMGPU(lr=0.0001, decay=1e-6, gdev_list=gpus_list)

    else:
        model = model_init
        print(model.summary())

        # initiate RMSprop optimizer
        opt = RMSprop(lr=0.0001, decay=1e-6)

    # Let's train the model using RMSprop
    model.compile(loss='categorical_crossentropy',
                  optimizer=opt,
                  metrics=['accuracy'])

    x_train = x_train.astype('float32')
    x_test = x_test.astype('float32')
    x_train /= 255
    x_test /= 255

    if not data_augmentation:
        print('Not using data augmentation.')
        model.fit(x_train, y_train,
                  batch_size=batch_size,
                  epochs=epochs,
                  validation_data=(x_test, y_test),
                  shuffle=True,
                  callbacks=callbacks)
    else:
        print('Using real-time data augmentation.')
        # This will do preprocessing and realtime data augmentation:
        datagen = ImageDataGenerator(
            featurewise_center=False,  # set input mean to 0 over the dataset
            samplewise_center=False,  # set each sample mean to 0
            # divide inputs by std of the dataset
            featurewise_std_normalization=False,
            samplewise_std_normalization=False,  # divide each input by its std
            zca_whitening=False,  # apply ZCA whitening
            # randomly rotate images in the range (degrees, 0 to 180)
            rotation_range=0,
            # randomly shift images horizontally (fraction of total width)
            width_shift_range=0.1,
            # randomly shift images vertically (fraction of total height)
            height_shift_range=0.1,
            horizontal_flip=True,  # randomly flip images
            vertical_flip=False)  # randomly flip images

        # Compute quantities required for feature-wise normalization
        # (std, mean, and principal components if ZCA whitening is applied).
        datagen.fit(x_train)

        # Fit the model on the batches generated by datagen.flow().
        model.fit_generator(datagen.flow(x_train, y_train,
                                         batch_size=batch_size),
                            steps_per_epoch=x_train.shape[0] // batch_size,
                            epochs=epochs,
                            validation_data=(x_test, y_test),
                            callbacks=callbacks)


if __name__ == '__main__':
    main()

