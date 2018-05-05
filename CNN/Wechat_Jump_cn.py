# coding: utf-8
'''
# === 思路 ===
# 核心：每次落稳之后截图，根据截图算出棋子的坐标和下一个块顶面的中点坐标，
#      根据两个点的距离乘以一个时间系数获得长按的时间
# 识别棋子：靠棋子的颜色来识别位置，通过截图发现最下面一行大概是一条直线，就从上往下一行一行遍历，
#      比较颜色（颜色用了一个区间来比较）找到最下面的那一行的所有点，然后求个中点，
#      求好之后再让 Y 轴坐标减小棋子底盘的一半高度从而得到中心点的坐标
# 识别棋盘：靠底色和方块的色差来做，从分数之下的位置开始，一行一行扫描，由于圆形的块最顶上是一条线，
#      方形的上面大概是一个点，所以就用类似识别棋子的做法多识别了几个点求中点，
#      这时候得到了块中点的 X 轴坐标，这时候假设现在棋子在当前块的中心，
#      根据一个通过截图获取的固定的角度来推出中点的 Y 坐标
# 最后：根据两点的坐标算距离乘以系数来获取长按时间（似乎可以直接用 X 轴距离）
'''

import os
import sys
import subprocess
import time
import math
from PIL import Image
import random
from six.moves import input
import cv2
import tensorflow as tf
import numpy as np


try:
    from common import debug, config
except ImportError:
    exit(-1)


VERSION = "1.1.1"


debug_switch = False    # debug 开关，需要调试的时候请改为：True
config = config.open_accordant_config()

# Magic Number，不设置可能无法正常执行，请根据具体截图从上到下按需设置，设置保存在 config 文件夹中
under_game_score_y = config['under_game_score_y']
press_coefficient = config['press_coefficient']       # 长按的时间系数，请自己根据实际情况调节
piece_base_height_1_2 = config['piece_base_height_1_2']   # 二分之一的棋子底座高度，可能要调节
piece_body_width = config['piece_body_width']             # 棋子的宽度，比截图中量到的稍微大一点比较安全，可能要调节


screenshot_way = 2


def pull_screenshot():
    '''
    新的方法请根据效率及适用性由高到低排序
    '''
    global screenshot_way
    if screenshot_way == 2 or screenshot_way == 1:
        process = subprocess.Popen('adb shell screencap -p', shell=True, stdout=subprocess.PIPE)
        screenshot = process.stdout.read()
        if screenshot_way == 2:
            binary_screenshot = screenshot.replace(b'\r\n', b'\n')
        else:
            binary_screenshot = screenshot.replace(b'\r\r\n', b'\n')
        f = open('autojump.png', 'wb')
        f.write(binary_screenshot)
        f.close()
    elif screenshot_way == 0:
        os.system('adb shell screencap -p /sdcard/autojump.png')
        os.system('adb pull /sdcard/autojump.png .')


def set_button_position(im):
    '''
    将 swipe 设置为 `再来一局` 按钮的位置
    '''
    global swipe_x1, swipe_y1, swipe_x2, swipe_y2
    w, h = im.size
    left = int(w / 2)
    top = int(1584 * (h / 1920.0))
    left = int(random.uniform(left-50, left+50))
    top = int(random.uniform(top-10, top+10))    # 随机防 ban
    swipe_x1, swipe_y1, swipe_x2, swipe_y2 = left, top, left, top


def jump(distance):
    '''
    跳跃一定的距离
    '''
    press_time = distance * press_coefficient
    press_time = max(press_time, 200)   # 设置 200ms 是最小的按压时间
    press_time = int(press_time)
    cmd = 'adb shell input swipe {x1} {y1} {x2} {y2} {duration}'.format(
        x1=swipe_x1,
        y1=swipe_y1,
        x2=swipe_x2,
        y2=swipe_y2,
        duration=press_time
    )
    print(cmd)
    os.system(cmd)
    return press_time


def find_piece_and_board(im):
    '''
    寻找关键坐标
    '''
    w, h = im.size

    piece_x_sum = 0
    piece_x_c = 0
    piece_y_max = 0
    board_x = 0
    board_y = 0
    scan_x_border = int(w / 8)  # 扫描棋子时的左右边界
    scan_start_y = 0  # 扫描的起始 y 坐标
    im_pixel = im.load()
    # 以 50px 步长，尝试探测 scan_start_y
    for i in range(int(h / 3), int(h*2 / 3), 50):
        last_pixel = im_pixel[0, i]
        for j in range(1, w):
            pixel = im_pixel[j, i]
            # 不是纯色的线，则记录 scan_start_y 的值，准备跳出循环
            if pixel[0] != last_pixel[0] or pixel[1] != last_pixel[1] or pixel[2] != last_pixel[2]:
                scan_start_y = i - 50
                break
        if scan_start_y:
            break
    #print('scan_start_y: {}'.format(scan_start_y))

    # 从 scan_start_y 开始往下扫描，棋子应位于屏幕上半部分，这里暂定不超过 2/3
    for i in range(scan_start_y, int(h * 2 / 3)):
        for j in range(scan_x_border, w - scan_x_border):  # 横坐标方面也减少了一部分扫描开销
            pixel = im_pixel[j, i]
            # 根据棋子的最低行的颜色判断，找最后一行那些点的平均值，这个颜色这样应该 OK，暂时不提出来
            if (50 < pixel[0] < 60) and (53 < pixel[1] < 63) and (95 < pixel[2] < 110):
                piece_x_sum += j
                piece_x_c += 1
                piece_y_max = max(i, piece_y_max)

    if not all((piece_x_sum, piece_x_c)):
        return 0, 0, 0, 0
    piece_x = int(piece_x_sum / piece_x_c)
    piece_y = piece_y_max - piece_base_height_1_2  # 上移棋子底盘高度的一半

    # 限制棋盘扫描的横坐标，避免音符 bug
    if piece_x < w/2:
        board_x_start = piece_x
        board_x_end = w
    else:
        board_x_start = 0
        board_x_end = piece_x

    for i in range(int(h / 3), int(h * 2 / 3)):
        last_pixel = im_pixel[0, i]
        if board_x or board_y:
            break
        board_x_sum = 0
        board_x_c = 0

        for j in range(int(board_x_start), int(board_x_end)):
            pixel = im_pixel[j, i]
            # 修掉脑袋比下一个小格子还高的情况的 bug
            if abs(j - piece_x) < piece_body_width:
                continue

            # 修掉圆顶的时候一条线导致的小 bug，这个颜色判断应该 OK，暂时不提出来
            if abs(pixel[0] - last_pixel[0]) + abs(pixel[1] - last_pixel[1]) + abs(pixel[2] - last_pixel[2]) > 10:
                board_x_sum += j
                board_x_c += 1
        if board_x_sum:
            board_x = board_x_sum / board_x_c
    last_pixel = im_pixel[board_x, i]

    # 从上顶点往下 +274 的位置开始向上找颜色与上顶点一样的点，为下顶点
    # 该方法对所有纯色平面和部分非纯色平面有效，对高尔夫草坪面、木纹桌面、药瓶和非菱形的碟机（好像是）会判断错误
    for k in range(i+274, i, -1): # 274 取开局时最大的方块的上下顶点距离
        pixel = im_pixel[board_x, k]
        if abs(pixel[0] - last_pixel[0]) + abs(pixel[1] - last_pixel[1]) + abs(pixel[2] - last_pixel[2]) < 10:
            break
    board_y = int((i+k) / 2)

    # 如果上一跳命中中间，则下个目标中心会出现 r245 g245 b245 的点，利用这个属性弥补上一段代码可能存在的判断错误
    # 若上一跳由于某种原因没有跳到正中间，而下一跳恰好有无法正确识别花纹，则有可能游戏失败，由于花纹面积通常比较大，失败概率较低
    for l in range(i, i+200):
        pixel = im_pixel[board_x, l]
        if abs(pixel[0] - 245) + abs(pixel[1] - 245) + abs(pixel[2] - 245) == 0:
            board_y = l+10
            break

    if not all((board_x, board_y)):
        return 0, 0, 0, 0

    return piece_x, piece_y, board_x, board_y


def check_screenshot():
    '''
    检查获取截图的方式
    '''
    global screenshot_way
    if os.path.isfile('autojump.png'):
        os.remove('autojump.png')
    if (screenshot_way < 0):
        print('暂不支持当前设备')
        sys.exit()
    pull_screenshot()
    try:
        Image.open('./autojump.png').load()
        print('采用方式 {} 获取截图'.format(screenshot_way))
    except Exception:
        screenshot_way -= 1
        check_screenshot()


def yes_or_no(prompt, true_value='y', false_value='n', default=True):
    default_value = true_value if default else false_value
    prompt = '%s %s/%s [%s]: ' % (prompt, true_value, false_value, default_value)
    i = input(prompt)
    if not i:
        return default
    while True:
        if i == true_value:
            return True
        elif i == false_value:
            return False
        prompt = 'Please input %s or %s: ' % (true_value, false_value)
        i = input(prompt)

def deepnn(x):
    """deepnn builds the graph for a deep net for classifying digits.
    Args:
    x: an input tensor with the dimensions (N_examples, 784), where 784 is the
    number of pixels in a standard MNIST image.
    Returns:
    A tuple (y, keep_prob). y is a tensor of shape (N_examples, 10), with values
    equal to the logits of classifying the digit into one of 10 classes (the
    digits 0-9). keep_prob is a scalar placeholder for the probability of
    dropout.
    """
    # Reshape to use within a convolutional neural net.
    # Last dimension is for "features" - there is only one here, since images are
    # grayscale -- it would be 3 for an RGB image, 4 for RGBA, etc.

    Hidden_fc1 = 1024
    Hidden_fc2 = 86
    Hidden_fc3 = 4

    with tf.name_scope('reshape'):
        x_image = tf.reshape(x, [-1, 51, 86, 1])

    # First convolutional layer - maps one grayscale image to 32 feature maps.
    with tf.name_scope('conv1'):
        W_conv1 = weight_variable([5, 5, 1, 64])
        b_conv1 = bias_variable([64])
        h_conv1 = tf.nn.relu(conv2d(x_image, W_conv1) + b_conv1)

    # Pooling layer - downsamples by 2X.
    with tf.name_scope('pool1'):
        h_pool1 = max_pool_2x2(h_conv1)

    # Second convolutional layer -- maps 32 feature maps to 64.
    with tf.name_scope('conv2'):
        W_conv2 = weight_variable([7, 7, 64, 32])
        b_conv2 = bias_variable([32])
        h_conv2 = tf.nn.relu(conv2d(h_pool1, W_conv2) + b_conv2)

    # Second pooling layer.
    with tf.name_scope('pool2'):
        h_pool2 = max_pool_2x2(h_conv2)

    # Fully connected layer 1 -- after 2 round of downsampling, our 28x28 image
    # is down to 7x7x64 feature maps -- maps this to 1024 features.
    with tf.name_scope('fc1'):
        W_fc1 = weight_variable([13 * 22 * 32, Hidden_fc1])
        b_fc1 = bias_variable([Hidden_fc1])

        h_pool2_flat = tf.reshape(h_pool2, [-1, 13 * 22 * 32])
        h_fc1 = tf.nn.relu(tf.matmul(h_pool2_flat, W_fc1) + b_fc1)

    # Dropout - controls the complexity of the model, prevents co-adaptation of
    # features.
    with tf.name_scope('dropout'):
        keep_prob = tf.placeholder(tf.float32)
        h_fc1_drop = tf.nn.dropout(h_fc1, keep_prob)

    with tf.name_scope('fc2'):
        W_fc2 = weight_variable([Hidden_fc1, Hidden_fc2])
        b_fc2 = bias_variable([Hidden_fc2])

        h_fc2 = tf.nn.relu(tf.matmul(h_fc1_drop, W_fc2) + b_fc2)

    # Dropout - controls the complexity of the model, prevents co-adaptation of
    # features.
    with tf.name_scope('dropout'):
        h_fc2_drop = tf.nn.dropout(h_fc2, keep_prob)

    # Map the 1024 features to 10 classes, one for each digit
    with tf.name_scope('fc3'):
        W_fc3 = weight_variable([Hidden_fc2, Hidden_fc3])
        b_fc3 = bias_variable([Hidden_fc3])

        y_conv = tf.matmul(h_fc2_drop, W_fc3) + b_fc3
        return y_conv, keep_prob


def conv2d(x, W):
    """conv2d returns a 2d convolution layer with full stride."""
    return tf.nn.conv2d(x, W, strides=[1, 1, 1, 1], padding='SAME')


def max_pool_2x2(x):
    """max_pool_2x2 downsamples a feature map by 2X."""
    return tf.nn.max_pool(x, ksize=[1, 2, 2, 1],
                    strides=[1, 2, 2, 1], padding='SAME')


def weight_variable(shape):
    """weight_variable generates a weight variable of a given shape."""
    initial = tf.truncated_normal(shape, stddev=0.1)
    return tf.Variable(initial)


def bias_variable(shape):
    """bias_variable generates a bias variable of a given shape."""
    initial = tf.constant(0.1, shape=shape)
    return tf.Variable(initial)

def main():
    '''
    主函数
    '''
    op = yes_or_no('请确保手机打开了 ADB 并连接了电脑，然后打开跳一跳并【开始游戏】后再用本程序，确定开始？')
    if not op:
        print('bye')
        return
    debug.dump_device_info()
    check_screenshot()


    x = tf.placeholder(tf.float32, [None, 51, 86])
    y_conv, keep_prob = deepnn(x)

    saver = tf.train.Saver()
    sess = tf.Session()
    saver.restore(sess, tf.train.latest_checkpoint('./TF_Saved_Model/'))

    Num = 0
    while(True):
        pull_screenshot()
        im = Image.open('./autojump.png')
        # 获取棋子和 board 的位置
        piece_x_o, piece_y_o, board_x_o, board_y_o = find_piece_and_board(im)

        """
        if i == next_rest:
            print('已经连续打了 {} 下，休息 {}s'.format(i, next_rest_time))
            for j in range(next_rest_time):
                sys.stdout.write('\r程序将在 {}s 后继续'.format(next_rest_time - j))
                sys.stdout.flush()
                time.sleep(1)
            print('\n继续')
            i, next_rest, next_rest_time = 0, random.randrange(1, 10), random.randrange(1, 10)
        """
        #time.sleep(random.uniform(1.9, 2.2))   # 为了保证截图的时候应落稳了，多延迟一会儿，随机值防 ban


        im_cv = cv2.imread('./autojump.png')
        im_cvrs = cv2.resize(im_cv, None, fx=ReshapeRatio1, fy=ReshapeRatio1, interpolation=cv2.INTER_CUBIC)
        im_cvrs_back = cv2.resize(im_cv, None, fx=ReshapeRatio1, fy=ReshapeRatio1, interpolation=cv2.INTER_CUBIC)

        H_org, W_org, _ = im_cv.shape
        H_rs_org, W_rs_org, _ = im_cvrs.shape
        print(H_org, W_org)

        Num = Num+1
        Name = str(int(piece_x_o*ReshapeRatio1))+'_'\
             + str(int(piece_y_o*ReshapeRatio1))+'_'\
             + str(int(board_x_o*ReshapeRatio1))+'_'\
             + str(int(board_y_o*ReshapeRatio1))+'_'\
             +str(Num)+".png"
        Path ='/home/zhy/Pic/'
        cv2.imwrite(Path+Name, im_cvrs, [int(cv2.IMWRITE_PNG_COMPRESSION), 9])

        im_cvrs = im_cvrs[250:506,:]

        im_cvrs_cnn = cv2.resize(im_cvrs, None, fx=ReshapeRatio2, fy=ReshapeRatio2, interpolation=cv2.INTER_CUBIC)
        im_cvrs_cnn_gray = cv2.cvtColor(im_cvrs_cnn, cv2.COLOR_BGR2GRAY)
        cv2.imshow('im_cvrs_cnn_gray', im_cvrs_cnn_gray)

        print(im_cvrs_cnn_gray.shape)

        im_cvrs_cnn_gray = (im_cvrs_cnn_gray-127)/255
        x_batch = im_cvrs_cnn_gray[np.newaxis,:,:]
        prediction = sess.run([y_conv],feed_dict={x: x_batch, keep_prob: 1})
        prediction = prediction[0][0]
        print('Prediction:\n', prediction)

        piece_x = int(prediction[0]*W_org)
        piece_y = int(prediction[1]*H_org)
        board_x = int(prediction[2]*W_org)
        board_y = int(prediction[3]*H_org)

        piece_x_rs = int(prediction[0]*W_rs_org)
        piece_y_rs = int(prediction[1]*H_rs_org)
        board_x_rs = int(prediction[2]*W_rs_org)
        board_y_rs = int(prediction[3]*H_rs_org)

        cv2.circle(im_cvrs_back, (piece_x_rs, piece_y_rs), 15, (255, 0, 0), -1)
        cv2.circle(im_cvrs_back, (board_x_rs, board_y_rs), 15, (0, 0, 255), -1)

        cv2.imshow('Image', im_cvrs_back)
        cv2.waitKey(500)

        ts = int(time.time())
        print(piece_x, piece_y, board_x, board_y)
        print(piece_x_o, piece_y_o, board_x_o, board_y_o)

        set_button_position(im)
        #if Num%100 == 99:
            #jump(math.sqrt((board_x - piece_x) ** 2 + (board_y - piece_y) ** 2))
        #else:
        jump(math.sqrt((board_x - piece_x) ** 2 + (board_y - piece_y) ** 2))
        if debug_switch:
            debug.save_debug_screenshot(ts, im, piece_x, piece_y, board_x, board_y)
            debug.backup_screenshot(ts)
        time.sleep(random.uniform(1.9, 2.2))   # 为了保证截图的时候应落稳了，多延迟一会儿，随机值防 ban


if __name__ == '__main__':
    ReshapeRatio1 = 0.4
    ReshapeRatio2 = 0.2
    main()