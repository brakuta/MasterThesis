from typing import Tuple

from keras.models import Model
from keras.optimizers import Adam
from keras_contrib.applications.densenet import DenseNetFCN


def fcndensenet(input_size: int, num_classes: int, channels: int = 3) -> Tuple[Model, str]:
    model = DenseNetFCN(input_shape=(input_size, input_size, channels), classes=num_classes)
    model_name = 'fcn_densenet'

    model.compile(optimizer=Adam(), loss='binary_crossentropy', metrics=['accuracy'])

    return model, model_name
