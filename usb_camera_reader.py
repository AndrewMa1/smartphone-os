import cv2
import numpy as np
import os
from datetime import datetime

capworld = cv2.VideoCapture(0)
# 使用 CAP_DSHOW 后端
capcam1 = cv2.VideoCapture(1, cv2.CAP_DSHOW) # 这里要添加一个参数
# 下面这两条语句缺一不可，原因不明
capcam1.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('m', 'j', 'p', 'g'))
capcam1.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
# 设置分辨率
capcam1.set(cv2.CAP_PROP_FRAME_WIDTH, 400)
capcam1.set(cv2.CAP_PROP_FRAME_HEIGHT, 400)

capcam2 = cv2.VideoCapture(2, cv2.CAP_DSHOW) # 这里要添加一个参数
# 下面这两条语句缺一不可，原因不明
capcam2.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('m', 'j', 'p', 'g'))
capcam2.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('M', 'J', 'P', 'G'))
# 设置分辨率
capcam2.set(cv2.CAP_PROP_FRAME_WIDTH, 400)
capcam2.set(cv2.CAP_PROP_FRAME_HEIGHT, 400)

# Recording state variables
is_recording = False
video_writers = None
record_folder = None

def create_record_folder():
    """Create a timestamped folder in the record directory"""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    record_dir = os.path.join("record", timestamp)
    os.makedirs(record_dir, exist_ok=True)
    return record_dir

def initialize_video_writers(record_dir):
    """Initialize video writers for the three cameras"""
    # Get frame properties for video writer setup
    ret1, frame_cam1 = capcam1.read()
    ret2, frame_cam2 = capcam2.read()
    ret3, frame_world = capworld.read()

    if not (ret1 and ret2 and ret3):
        return None
    
    # Apply transformations to get actual frame dimensions
    frame_world = cv2.flip(frame_world, 0)
    frame_world = cv2.flip(frame_world, 1)
    frame_cam1 = cv2.rotate(frame_cam1, cv2.ROTATE_90_CLOCKWISE)
    frame_cam2 = cv2.rotate(frame_cam2, cv2.ROTATE_90_CLOCKWISE)
    
    # Define codec and fps
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = 30.0
    
    # Initialize video writers
    eye0_writer = cv2.VideoWriter(
        os.path.join(record_dir, "eye0.mp4"),
        fourcc, fps, 
        (frame_cam1.shape[1], frame_cam1.shape[0])
    )
    
    eye1_writer = cv2.VideoWriter(
        os.path.join(record_dir, "eye1.mp4"),
        fourcc, fps,
        (frame_cam2.shape[1], frame_cam2.shape[0])
    )
    
    world_writer = cv2.VideoWriter(
        os.path.join(record_dir, "world.mp4"),
        fourcc, fps,
        (frame_world.shape[1], frame_world.shape[0])
    )
    
    return eye0_writer, eye1_writer, world_writer

print("按 'c' 开始录制，按 'q' 停止录制并退出")

while True:
    ret1, frame_cam1 = capcam1.read()
    ret2, frame_cam2 = capcam2.read()
    ret3_world, frame_world = capworld.read()
    frame_world = cv2.flip(frame_world, 0)
    frame_world = cv2.flip(frame_world, 1)
    frame_cam1 = cv2.rotate(frame_cam1, cv2.ROTATE_90_CLOCKWISE)
    frame_cam2 = cv2.rotate(frame_cam2, cv2.ROTATE_90_CLOCKWISE)


    if not ret1 or not ret2 or not ret3_world:
        print("错误：无法接收帧。")
        break

    f1s = cv2.resize(frame_cam1, (320, 240))
    f2s = cv2.resize(frame_cam2, (320, 240))
    ws  = cv2.resize(frame_world, (320, 240))
    combined = np.hstack([f1s, f2s, ws])
    
    # Add recording status text to display
    status_text = "Recording..." if is_recording else "Press 'c' to start recording"
    cv2.putText(combined, status_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0) if is_recording else (255, 255, 255), 2)
    
    cv2.imshow("Eye0 | Eye1 | World", combined)
    
    # Write frames if recording
    if is_recording and video_writers is not None:
        eye0_writer, eye1_writer, world_writer = video_writers
        eye0_writer.write(frame_cam1)
        eye1_writer.write(frame_cam2)
        world_writer.write(frame_world)

    key = cv2.waitKey(1) & 0xFF
    
    # Handle key presses
    if key == ord('c') and not is_recording:
        # Start recording
        record_folder = create_record_folder()
        video_writers = initialize_video_writers(record_folder)
        if video_writers is not None:
            is_recording = True
            print(f"开始录制到文件夹: {record_folder}")
        else:
            print("错误: 无法初始化视频录制器")
    
    elif key == ord('q'):
        # Stop recording and quit
        if is_recording and video_writers is not None:
            eye0_writer, eye1_writer, world_writer = video_writers
            eye0_writer.release()
            eye1_writer.release()
            world_writer.release()
            print(f"录制完成，文件保存在: {record_folder}")
        break

capcam1.release()
capcam2.release()
capworld.release()
cv2.destroyAllWindows()
'''
世界坐标系标定板 变换到 近眼相机坐标系标定板
(1,0,0)     (0,0,1)
(0,1,0)     (0,-1,0)
(0,0,1)   ->(1,0,0)
R = np.array([0,0,1],[0,-1,0],[1,0,0])
t = np.array([246.5,2,64])
x   20*10+45+1.5 = 246.5
y   12+5-15
z   -(4+5+11*5)
'''
