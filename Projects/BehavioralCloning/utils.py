import numpy as np
import cv2
import pandas as pd

from sklearn.model_selection import train_test_split
from sklearn.utils import shuffle
from decorators import n_images


def load_data(path, file):
    """
    Opens driving_log.csv and returns center, left, right, and steering in a dictionary.

    :param path: Full file path to file
    :param file: The name of the file to load

    :type path: String
    :type file: String

    :return: Dictionary containing the camera file paths and steering angles.
    :rtype: Dictionary with keys = ['angles', 'center', 'left', 'right']
    """
    df = pd.read_csv(path + file, names=['CenterImage', 'LeftImage', 'RightImage', 'SteeringAngle',
                                         'Throttle', 'Break', 'Speed'])
    data = {
        'angles': df['SteeringAngle'].astype('float32').as_matrix(),
        'center': np.array([path + str(im).replace(' ', '').replace('\\', '/') for im in df['CenterImage'].as_matrix()]),
        'right': np.array([path + str(im).replace(' ', '').replace('\\', '/') for im in df['RightImage'].as_matrix()]),
        'left': np.array([path + str(im).replace(' ', '').replace('\\', '/') for im in df['LeftImage'].as_matrix()])
      }
    return data


def concat_all_cameras(data, angle_shift, condition_lambda, keep_percent):
    # Remove n% of the frames where the steering angle is close to zero
    ims, angles = keep_n_percent_of_data_where(
        data=np.array([data['center'], data['right'], data['left']]).T,
        values=data['angles'],
        condition_lambda=condition_lambda,
        percent=keep_percent
    )
    center_ims = [im for im in ims[..., 0]]
    right_ims = [im for im in ims[..., 1]]
    left_ims = [im for im in ims[..., 2]]

    # Modify the steering angles of the left and right cameras's images to simulate
    # steering back towards the middle. Aggregate all sets into one.
    filtered_images = np.concatenate((center_ims, right_ims, left_ims), axis=0)
    filtered_angles = np.concatenate((angles, angles + angle_shift, angles - angle_shift), axis=0)
    return filtered_images, filtered_angles


def keep_n_percent_of_data_where(data, values, condition_lambda, percent):
    """
    Keeps n-percent of a dataset where a condition over the values is true.

    For example, if you want to remove 90% of the samples in a dataset where the steering angles are
    close to zero, the code would look like this:

        images, angles = keep_n_percent_of_data_where(images, angles, lambda x: abs(x) < 1e-5, 0.1)

    Note that the lambda should return True for the values you would like to filter.

    :param data: The dataset
    :param values: The values to filter over
    :param condition_lambda: A lambda by which to filter the dataset
    :param percent: The percent of the dataset-value pair (where `condition_lambda` is true) to KEEP

    :type data: np.ndarray
    :type values: np.ndarray
    :type condition_lambda: lambda or function
    :type percent: float

    :return: Filtered tuple: (filtered_data, filtered_values)
    :rtype: Tuple
    """
    assert data.shape[0] == values.shape[0], 'Different # of data points and values.'

    cond_true = condition_lambda(values)
    data_true, data_false = data[cond_true, ...], data[~cond_true, ...]
    val_true, val_false = values[cond_true], values[~cond_true]

    cutoff = int(percent * data_true.shape[0])
    # Shuffle before clipping the top (1-n)%
    data_true, val_true = shuffle(data_true, val_true)
    # Only keep n% of the data points where the condition is true
    clipped_data_true, clipped_val_true = data_true[:cutoff, ...], val_true[:cutoff]

    filtered_data = np.concatenate((data_false, clipped_data_true), axis=0)
    filtered_values = np.concatenate((val_false, clipped_val_true), axis=0)

    return filtered_data, filtered_values


def split_data(features, labels, test_size=0.2, shuffle_return=True):
    """
    Splits the dataset and labels into training and testing sets, with proportions (1-test_size) and test_size.

    :param features: The dataset to split
    :param labels: The labels for the dataset
    :param test_size: The proportion of the dataset to siphon into the test set
    :param shuffle_return: If True, shuffles the dataset and labels before splitting
    :return: (X_train, X_test, y_train, y_test)
    """
    if shuffle_return:
        features, labels = shuffle(features, labels)
    return train_test_split(features, labels, test_size=test_size)


def process_image(im):
    """
    Grayscale the image and normalize its pixels to [-0.5, 0.5]

    :param im: Image to normalize
    :return: Normalized image with shape (h, w, 1)

    :type im: np.ndarray with shape (h, w, 3)
    :rtype: np.ndarray with shape (h, w, 1)
    """
    assert im.ndim == 3 and im.shape[2] == 3, 'Must be a BGR image with shape (h, w, 3)'

    im = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    im = im[40:130, :]
    im = cv2.resize(im, (200, 66))

    if im.ndim == 2:
        im = np.expand_dims(im, -1)
    return im


@n_images  # Decorator to generalize single image method to multiple images
def flip_image(image, angle):
    """
    Mirrors the image from left to right and flips the sign of the angle.

    :param image: Image to flip
    :param angle: Angle to flip
    :return: (flipped_images, flipped_angle)
    """
    flipped = cv2.flip(image, 1)
    if flipped.ndim == 2:
        flipped = np.expand_dims(flipped, -1)
    return flipped, -angle


def val_augmentor(ims, vals):
    """
    Normalizes images/vals into first set, flips and concats into second set, concats both sets, and returns.

    :param ims: Images to normalize/flip
    :param vals: Angles to normalize/flip
    :return: (normalized/flipped images, normalized/flipped angles)
    """
    normalized = np.array([process_image(im) for im in ims])
    flipped_ims, flipped_vals = flip_image(normalized, vals)
    return np.concatenate((normalized, flipped_ims), axis=0), \
           np.concatenate((vals, flipped_vals), axis=0)


@n_images  # Decorator to generalize single image method to multiple images
def augment_image(image, value, prob, im_normalizer=process_image):
    """
    Augments an image and steering angle with probability `prob`.

    This technique randomly adjusts the brightness, occludes the image with 30 random black squares,
    and slightly rotates, shifts and scales the image. These augmentations are meant to make the
    model more robust to conditions different to those in the training set.

    :param image: The image to augment
    :param value: The steering angle associated with the image
    :param prob: The probability of augmenting the image
    :param im_normalizer: Function to normalize the image
    :return: Tuple with (augmented_image, augmented_value)

    :type image: np.ndarray
    :type value: float
    :type prob: float [0.0, 1.0]
    :type im_normalizer: function
    :rtype: tuple with values (augmented_image, augmented_value)
    """
    assert image.ndim == 3, 'Image must have dimensions (h, w, ch)'

    image = im_normalizer(image)

    h, w = image.shape[:2]

    # Flip the image and angle half the time. Effectively doubles the size of
    # the dataset while balancing the left and right turn proportions.
    if np.random.uniform(0.0, 1.0) < 0.5:
        image, value = cv2.flip(image, 1), -value
        image = np.expand_dims(image, -1)

    # Return un-augmented image and value with probability (1-prob)
    if np.random.uniform(0.0, 1.0) > prob:
        return image, value

    # Random occlusion with dark squares
    # sq_w, sq_h, sq_count = int(0.15*h), int(0.15*h), 30
    # for i in range(sq_count):
    #     pt1 = (np.random.randint(0, w), np.random.randint(0, h))
    #     pt2 = (pt1[0] + sq_w, pt1[1] + sq_h)
    #     cv2.rectangle(image, pt1, pt2, (-0.5, -0.5, -0.5), -1)

    # Random shadow simulation
    image = image.astype(np.float32)

    top_y, bot_y = np.random.randint(0, w, size=2)
    XX, YY = np.mgrid[0:h, 0:w]
    shadow = np.zeros_like(image, dtype=np.float32)
    shadow[XX*(bot_y-top_y) - h*(YY-top_y) >= 0.0] = 1

    mask = shadow == np.random.randint(0, 2)
    image[mask] *= np.random.uniform(0.4, 1.0)

    # Randomly augment total brightness
    image *= np.random.uniform(0.6, 1.0)

    image.astype(np.uint8)

    # Rotation/Scaling matrix
    rotation, scale = 1, 0.02
    M_rot = cv2.getRotationMatrix2D(
        (h//2, w//2),
        np.random.uniform(-rotation, rotation),
        np.random.uniform(1.0 - scale, 1.0 + scale)
      )

    # Shifts/Affine transforms
    src = np.array([[0,0], [w,0], [w,h]]).astype('float32')

    pixel_shift = 2
    x_shift = np.random.randint(-pixel_shift, pixel_shift)
    y_shift = np.random.randint(-pixel_shift, pixel_shift)

    dst = np.array([
        [0 + x_shift, 0 + y_shift],
        [w + x_shift, 0 + y_shift],
        [w + x_shift, h + y_shift]
      ]).astype('float32')

    M_affine = cv2.getAffineTransform(src, dst)

    # Apply augmentations to the image
    augmented = cv2.warpAffine(image, M_rot, (w,h))
    augmented = cv2.warpAffine(augmented, M_affine, (w,h))

    # Ensure there is a color channel
    if augmented.ndim < 3:
        augmented = np.expand_dims(augmented, -1)

    # Add random noise to steering angle
    rand_ang = 0.001
    value += np.random.uniform(-rand_ang, rand_ang)
    return augmented, value


def batch_generator(ims, angs, batch_size, augmentor, path, kwargs={}, validation=False):
    """
    Continuously generates batches from the provided images paths and angles.

    This method follows this process. Generates a batch of size `batch_size` in sequential order through
    the data. It is important that the data is shuffled prior to being fed into the generator. If the
    dataset is not evenly divisible by the batch size, their will be an orphan batch at the end. To
    address this, data is randomly selected to fill the batch. This option can be disabled by setting
    `validation` to True. Once the batch has been constructed, the images are loaded from the image paths
    using `cv2.imread`. Note that this means the images will be read in BGR format. Lastly, the images
    and angles are fed into the provided augmentation function, `augmentor`, and then yielded.

    :param ims: The filepaths to the images
    :param angs: The steering angles corresponding to the image paths
    :param batch_size: The size of batches to generate
    :param augmentor: A function which takes inputs (images, angles, **kwargs)
                      and returns (images, angles)
    :param path: A filepath which will be appended to the beginning of each image path
    :param kwargs: A dictionary containing any additional argument-value pairs for the
                   `augmentor` function
    :param validation: A boolean indicating whether or not to expand the orphan batch
                       from the generator. See description above.
    :return: Generator producing an infinite number of batches adhering to the above policies
    """
    n_obs = ims.shape[0]
    assert n_obs == angs.shape[0], 'Different # of data and labels.'

    while True:
        for batch in range(0, n_obs, batch_size):
            next_idx = batch + batch_size
            batch_x = ims[batch:min(next_idx, n_obs), ...]
            batch_y = angs[batch:min(next_idx, n_obs), ...]

            # Ensure consistent batch size by adding random images to the last
            # batch iff n_obs % batch_size != 0.
            if next_idx > n_obs and not validation:
                rand_idx = np.random.randint(0, n_obs-1, next_idx - n_obs)
                batch_x = np.concatenate((batch_x, ims[rand_idx, ...]), axis=0)
                batch_y = np.concatenate((batch_y, angs[rand_idx, ...]), axis=0)

            # Load the images from their paths
            batch_x = np.array([cv2.imread(path + im) for im in batch_x])
            # Augment the images with the given function
            batch_x, batch_y = augmentor(batch_x, batch_y, **kwargs)
            yield batch_x, batch_y
