import cv2
import numpy as np
import time
from ultralytics import YOLO
from ugot import ugot
import argparse
import logging

logging.getLogger("yolov8").setLevel(logging.WARNING)

logging.getLogger("yolov5").setLevel(logging.WARNING)

parser = argparse.ArgumentParser()
parser.add_argument('--weights', default='./models/best0907_2.pt', type=str)
# parser.add_argument('--weights', default='./models/yolov8n.pt', type=str)
parser.add_argument('--source', default=0, type=str)
parser.add_argument('--device', type=int, default=0)
parser.add_argument('--img', nargs='+', type=int, default=480, help='[train, test] image sizes')
parser.add_argument('--conf', type=float, default=0.5, help='object confidence threshold')
parser.add_argument('--iou', type=float, default=0.45, help='IOU threshold for NMS')
arg = parser.parse_args()


# PID
class PIDController:
    def __init__(self,kp,ki,kd):
        self.last_error = 0
        self.integral = 0
        self.kp = kp
        self.ki = ki
        self.kd = kd
    
    def update(self, error):
        self.integral += error
        derivative = error - self.last_error
        self.last_error = error
        
        output = self.kp * error + self.ki * self.integral + self.kd * derivative       
   
        return output
    
def load_yolov8_model():
    model = YOLO(arg.weights) 
    return model

def detect_objects(image, model):
    
    results = model.predict(image,
                            save=False,
                            imgsz=arg.img,
                            device=0,
                            conf=arg.conf,
                            stream=True,
                            iou=arg.iou
                            )
    
    
    # annotated_frame = results[0].plot()
        
     # output results
    boxes = []
    confidences = []
    class_names = []
    
    for r in results:
        if len(r.boxes.xyxy) == 0:
            continue
        for box in r.boxes:
            cords = box.xyxy[0].tolist()
            # pos = box.xywh[0].tolist()
            class_id = box.cls[0].item()
            box_conf = box.conf[0].item()
            class_name = r.names[int(class_id)]
            boxes.append(cords)
            confidences.append(box_conf)
            class_names.append(class_name)    

    return boxes, confidences, class_names

# Determine whether the target object is on the left or right side of the car, and control the car's steering.
def track_object_position(target_x, image_width):    
    turnValue = 20
    error = target_x - image_width // 2
    control = turn_pid_controller.update(error)   
    print("control:",control," diff:",target_x - image_width / 2)
    pos = ""
    if target_x < (image_width // 2 - 50):     
        got.mecanum_motor_control(-turnValue, turnValue, -turnValue, turnValue)
        pos = "left"
    elif target_x > (image_width // 2 + 50):
        pos = "right"              
        got.mecanum_motor_control(turnValue, -turnValue, turnValue, -turnValue)
    else:
        got.mecanum_stop()    
        pos = "center"
    return pos     

# Determining the distance of an object based on the height of the frame and calling the car to move forward or backward to achieve tracking.
def follow_target_distance_height(height):
    value = 10
    # PID
    # error = box_area - 160000 // 2
    # value = move_pid_controller.update(error)
    # value = int(abs(value))
    # print("value:",value," diff:",error)
    
    control = True
    dis = ""
    if height < 130000:        
        got.mecanum_motor_control(value, value, value, value)
        dis = "far"
    elif height > 160000:
        got.mecanum_motor_control(-value, -value, -value, -value)
        dis = "near"
    else:
        got.mecanum_stop() 
        dis = "center"
        
def follow_target_distance(distance):
    #40~60cm is the moderate distance.
    #50~250cm is the optimal distance for camera object recognition.
    # Therefore, the maximum value of error is approximately 200.
    maxSpeed = 200
    error = distance - 50
    value = move_pid_controller.update(error)
    print("controlValue:",value," distance - 50:",error)     
    speed = maxSpeed * value / 200
    speed = int(speed)
    print("speed:",speed) 
    if speed > 0 and speed < 18: speed = 18
    if speed < 0 and speed > -18: speed = -18
    if distance > 60:
        got.mecanum_motor_control(speed, speed, speed, speed)
    elif distance < 40:
        got.mecanum_motor_control(speed, speed, speed, speed)
    else:
        got.mecanum_stop()
   
if __name__ == '__main__':
    model = load_yolov8_model()  # Load YOLOv8 model
    got = ugot.UGOT()              # Init Ugot
    got.initialize("192.168.50.45") 
    got.mecanum_stop()
    got.read_distance_data(21) #40~60
    

    # cap = cv2.VideoCapture("rtsp://192.168.50.45:8554/unicast") 
    cap = cv2.VideoCapture("rtsp://192.168.50.45:8554/cam") 
    # cap = cv2.VideoCapture(0) 
    frame_interval = 3  # Set the processing interval frames.
    frame_count = 0
    disappear_count = 0
    turn_pid_controller = PIDController(0,0,0.1)  # PID object for turn 
    move_pid_controller = PIDController(1,0,0.1)  # PID object for move 

    while True:
        ret, frame = cap.read()  # read frame       
        if ret:            
            boxes, confidences, class_names = detect_objects(frame, model)  # detect
            if len(boxes) > 0:
                disappear_count = 0
                x1, y1, x2, y2 = boxes[0]
                x1,y1,x2,y2 = int(x1), int(y1), int(x2), int(y2)
                box_area = (x2-x1) * (y2-y1)

                cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 0, 0), 2)
                cv2.putText(frame, str(class_names[0]), (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
                cv2.putText(frame, "dis:{},height:{}".format(got.read_distance_data(21),(y2-y1)), (x1, y2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
                # print('box_area:', box_area)
                print('class_names:', class_names[0])
                # print('x:', x, 'y:', y, 'w:', w, 'h:', h)

                target_x = x1 + (x2-x1) // 2
                image_width = frame.shape[1]
                pos = ""
                if target_x < (image_width // 2 - 50): pos = "left"                                      
                elif target_x > (image_width // 2 + 50): pos = "right"                    
                else: pos = "center"                    
                cv2.putText(frame, pos, ( x1+(x2-x1)//2-15, y1+(y2-y1)//2 - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)                                               
                   
                frame_count += 1
                if frame_count % frame_interval == 0:
                    frame_count = 0
                    posistion = track_object_position(target_x, image_width)
                  
                    if posistion == "center":
                        follow_target_distance(got.read_distance_data(21))
            else:
            #     frame_count += 1
            #     if frame_count % frame_interval == 0:
            #         frame_count = 0                    
            #         disappear_count += 1
            #         if disappear_count == 200:
            #             got.mecanum_stop()
            #         elif disappear_count > 200:  
            #             turnValue = 10  
            #             got.mecanum_motor_control(-turnValue, turnValue, -turnValue, turnValue)
                got.mecanum_stop()
                    
            # Show image
            cv2.imshow("Object Tracking", frame)
    
            # 'q' quit
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        else:
            print(ret)
    cap.release()  
    cv2.destroyAllWindows()  
                

