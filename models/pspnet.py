from math import ceil
from typing import Tuple

from keras import layers
from keras import backend as keras_backend
from keras.layers import Conv2D, MaxPooling2D, AveragePooling2D
from keras.layers import BatchNormalization, Activation, Input, Dropout, ZeroPadding2D
from keras.layers.merge import Concatenate, Add
from keras.models import Model
from keras.optimizers import Adam
from keras.backend import tf as ktf
from keras_contrib.losses import jaccard_distance

from utils.metrics import dice_coefficient

learning_rate = 1e-3


def pspnet(input_size: int, num_classes: int, loss, channels: int = 3) -> Tuple[Model, str]:
    """
    Pyramid Scene Parsing Network

    https://arxiv.org/abs/1612.01105
    https://hszhao.github.io/projects/pspnet/
    https://github.com/Vladkryvoruchko/PSPNet-Keras-tensorflow
    """
    inputs = Input((input_size, input_size, channels))
    resnet = resnet50(inputs)
    psp = build_pyramid_pooling_module(resnet, (input_size, input_size))

    x = Conv2D(512, (3, 3), padding="same", name="conv5_4", use_bias=False)(psp)
    x = batchnorm(name="conv5_4_bn")(x)
    x = Activation('relu')(x)
    x = Dropout(0.1)(x)

    x = Conv2D(num_classes, (1, 1), name="conv6")(x)
    x = Interp([input_size, input_size])(x)
    x = Activation('sigmoid')(x)

    model = Model(inputs=inputs, outputs=x)
    model.compile(optimizer=Adam(), sloss=loss, metrics=[dice_coefficient, jaccard_distance, 'accuracy'])

    return model, "PSPNet"


def batchnorm(name=""):
    return BatchNormalization(momentum=0.95, name=name, epsilon=1e-5)


class Interp(layers.Layer):

    def __init__(self, new_size, **kwargs):
        self.new_size = new_size
        super(Interp, self).__init__(**kwargs)

    def build(self, input_shape):
        super(Interp, self).build(input_shape)

    def call(self, inputs, **kwargs):
        new_height, new_width = self.new_size
        resized = ktf.image.resize_images(inputs, [new_height, new_width], align_corners=True)
        return resized

    def compute_output_shape(self, input_shape):
        return tuple([None, self.new_size[0], self.new_size[1], input_shape[3]])

    def get_config(self):
        config = super(Interp, self).get_config()
        config['new_size'] = self.new_size
        return config


def residual_conv(prev, level, pad=1, lvl=1, sub_lvl=1, modify_stride=False):
    lvl = str(lvl)
    sub_lvl = str(sub_lvl)
    names = ["conv" + lvl + "_" + sub_lvl + "_1x1_reduce",
             "conv" + lvl + "_" + sub_lvl + "_1x1_reduce_bn",
             "conv" + lvl + "_" + sub_lvl + "_3x3",
             "conv" + lvl + "_" + sub_lvl + "_3x3_bn",
             "conv" + lvl + "_" + sub_lvl + "_1x1_increase",
             "conv" + lvl + "_" + sub_lvl + "_1x1_increase_bn"]
    if modify_stride is False:
        prev = Conv2D(64 * level, (1, 1), strides=(1, 1), name=names[0], use_bias=False)(prev)
    elif modify_stride is True:
        prev = Conv2D(64 * level, (1, 1), strides=(2, 2), name=names[0], use_bias=False)(prev)

    prev = batchnorm(name=names[1])(prev)
    prev = Activation('relu')(prev)

    prev = ZeroPadding2D(padding=(pad, pad))(prev)
    prev = Conv2D(64 * level, (3, 3), strides=(1, 1), dilation_rate=pad, name=names[2], use_bias=False)(prev)

    prev = batchnorm(name=names[3])(prev)
    prev = Activation('relu')(prev)
    prev = Conv2D(256 * level, (1, 1), strides=(1, 1), name=names[4], use_bias=False)(prev)
    prev = batchnorm(name=names[5])(prev)
    return prev


def short_convolution_branch(prev, level, lvl=1, sub_lvl=1, modify_stride=False):
    lvl = str(lvl)
    sub_lvl = str(sub_lvl)
    names = ["conv" + lvl + "_" + sub_lvl + "_1x1_proj",
             "conv" + lvl + "_" + sub_lvl + "_1x1_proj_bn"]

    if modify_stride is False:
        prev = Conv2D(256 * level, (1, 1), strides=(1, 1), name=names[0], use_bias=False)(prev)
    elif modify_stride is True:
        prev = Conv2D(256 * level, (1, 1), strides=(2, 2), name=names[0], use_bias=False)(prev)

    prev = batchnorm(name=names[1])(prev)
    return prev


def empty_branch(prev):
    return prev


def residual_short(prev_layer, level, pad=1, lvl=1, sub_lvl=1, modify_stride=False):
    prev_layer = Activation('relu')(prev_layer)
    block_1 = residual_conv(prev_layer, level, pad=pad, lvl=lvl, sub_lvl=sub_lvl, modify_stride=modify_stride)

    block_2 = short_convolution_branch(prev_layer, level, lvl=lvl, sub_lvl=sub_lvl, modify_stride=modify_stride)
    added = Add()([block_1, block_2])
    return added


def residual_empty(prev_layer, level, pad=1, lvl=1, sub_lvl=1):
    prev_layer = Activation('relu')(prev_layer)

    block_1 = residual_conv(prev_layer, level, pad=pad, lvl=lvl, sub_lvl=sub_lvl)
    block_2 = empty_branch(prev_layer)
    added = Add()([block_1, block_2])
    return added


def resnet50(inp):
    with keras_backend.name_scope("ResNet_50"):
        # Names for the first couple layers of model
        names = ["conv1_1_3x3_s2",
                 "conv1_1_3x3_s2_bn",
                 "conv1_2_3x3",
                 "conv1_2_3x3_bn",
                 "conv1_3_3x3",
                 "conv1_3_3x3_bn"]

        # Short branch(only start of network)

        cnv1 = Conv2D(64, (3, 3), strides=(2, 2), padding='same', name=names[0], use_bias=False)(inp)  # "conv1_1_3x3_s2"
        bn1 = batchnorm(name=names[1])(cnv1)  # "conv1_1_3x3_s2/bn"
        relu1 = Activation('relu')(bn1)  # "conv1_1_3x3_s2/relu"

        cnv1 = Conv2D(64, (3, 3), strides=(1, 1), padding='same', name=names[2], use_bias=False)(relu1)  # "conv1_2_3x3"
        bn1 = batchnorm(name=names[3])(cnv1)  # "conv1_2_3x3/bn"
        relu1 = Activation('relu')(bn1)  # "conv1_2_3x3/relu"

        cnv1 = Conv2D(128, (3, 3), strides=(1, 1), padding='same', name=names[4], use_bias=False)(relu1)  # "conv1_3_3x3"
        bn1 = batchnorm(name=names[5])(cnv1)  # "conv1_3_3x3/bn"
        relu1 = Activation('relu')(bn1)  # "conv1_3_3x3/relu"

        res = MaxPooling2D(pool_size=(3, 3), padding='same', strides=(2, 2))(relu1)  # "pool1_3x3_s2"

        # ---Residual layers(body of network)

        """
        Modify_stride --Used only once in first 3_1 convolutions block.
        changes stride of first convolution from 1 -> 2
        """

        # 2_1- 2_3
        res = residual_short(res, 1, pad=1, lvl=2, sub_lvl=1)
        for i in range(2):
            res = residual_empty(res, 1, pad=1, lvl=2, sub_lvl=i + 2)

        # 3_1 - 3_3
        res = residual_short(res, 2, pad=1, lvl=3, sub_lvl=1, modify_stride=True)
        for i in range(3):
            res = residual_empty(res, 2, pad=1, lvl=3, sub_lvl=i + 2)
        # 4_1 - 4_6
        res = residual_short(res, 4, pad=2, lvl=4, sub_lvl=1)
        for i in range(5):
            res = residual_empty(res, 4, pad=2, lvl=4, sub_lvl=i + 2)

        # 5_1 - 5_3
        res = residual_short(res, 8, pad=4, lvl=5, sub_lvl=1)
        for i in range(2):
            res = residual_empty(res, 8, pad=4, lvl=5, sub_lvl=i + 2)

        res = Activation('relu')(res)
        return res


def interp_block(prev_layer, level, feature_map_shape, input_shape):
    # with keras_backend.name_scope('Pyramid_Level_{}'.format(level)):
    if input_shape == (473, 473):
        kernel_strides_map = {1: 60,
                              2: 30,
                              3: 20,
                              6: 10}
    elif input_shape == (713, 713):
        kernel_strides_map = {1: 90,
                              2: 45,
                              3: 30,
                              6: 15}
    else:
        raise Exception("Pooling parameters for input shape {} are not defined.".format(input_shape))

    names = [
        "conv5_3_pool" + str(level) + "_conv",
        "conv5_3_pool" + str(level) + "_conv_bn"
    ]
    kernel = (kernel_strides_map[level], kernel_strides_map[level])
    strides = (kernel_strides_map[level], kernel_strides_map[level])
    prev_layer = AveragePooling2D(kernel, strides=strides)(prev_layer)
    prev_layer = Conv2D(512, (1, 1), strides=(1, 1), name=names[0], use_bias=False)(prev_layer)
    prev_layer = batchnorm(name=names[1])(prev_layer)
    prev_layer = Activation('relu')(prev_layer)
    # prev_layer = Lambda(Interp, arguments={
    #                    'shape': feature_map_shape})(prev_layer)
    prev_layer = Interp(feature_map_shape)(prev_layer)
    return prev_layer


def build_pyramid_pooling_module(res, input_shape):
    """Build the Pyramid Pooling Module."""

    with keras_backend.name_scope("Pyramid_Pooling_Module"):
        # ---PSPNet concat layers with Interpolation
        feature_map_size = tuple(int(ceil(input_dim / 8.0))
                                 for input_dim in input_shape)
        print("PSP module will interpolate to a final feature map size of %s" % (feature_map_size, ))

        interp_block1 = interp_block(res, 1, feature_map_size, input_shape)
        interp_block2 = interp_block(res, 2, feature_map_size, input_shape)
        interp_block3 = interp_block(res, 3, feature_map_size, input_shape)
        interp_block6 = interp_block(res, 6, feature_map_size, input_shape)

        # concat all these layers. resulted
        # shape=(1,feature_map_size_x,feature_map_size_y,4096)
        res = Concatenate()([res,
                             interp_block6,
                             interp_block3,
                             interp_block2,
                             interp_block1])
        return res
