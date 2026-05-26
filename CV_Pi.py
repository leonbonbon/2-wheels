#CV for Pi
import cv2 as cv2
from ultralytics import YOLO
import asyncio
import time
#import numpy as np

robot_state = {
    "steering_command": "CENTERED"
}

model = YOLO("yolo26n.pt")

# print("Warming up")
# dummy_frame = np.zeros((160, 160, 3), dtype=np.uint8)
# model.predict(source=dummy_frame, verbose=False)
# print("Warmup complete!")

cap = cv2.VideoCapture(1)
width = 320
cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
height = 240
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)

target_fps = 10
frame_int = 1.0 / target_fps

async def Vision_Loop():
    print("Vision Loop Started. Press 'q' in the window to quit.")

    while True:
        start_time = time.time()

        ret, frame = cap.read()
        
        if not ret:
            print("Failed to grab hardware frame. Retrying...")
            await asyncio.sleep(0.01)
            continue

        results = model.predict(source=frame, imgsz=160, conf=0.35, classes=[0], verbose=False)
        for result in results:
            box = result.boxes
            if len(box) > 0:
                x1, y1, x2, y2 = box.xyxy[0]
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                #centering
                delta = int(320 * .05)
                cv2.line(frame, (((width//2) - delta),0), (((width//2) - delta),height), (255, 0, 0), 2)
                cv2.line(frame, (((width//2) + delta),0), (((width//2) + delta),height), (255, 0, 0), 2)
                x_avg = (x1 + x2) //2
                #y_avg = (y1 + y2) //2

                if x_avg > ((width//2) + delta) :
                    cv2.putText(frame, "right", ((width//2),(height//2)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 , (0, 0, 255), 2)
                    robot_state["steering_command"] = "TURN_RIGHT"
                elif x_avg < ((width//2) - delta):
                    cv2.putText(frame, "left", ((width//2),(height//2)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 , (0, 0, 255), 2)
                    robot_state["steering_command"] = "TURN_LEFT"
                else:
                    cv2.putText(frame, "centered", ((width//2),(height//2)), cv2.FONT_HERSHEY_SIMPLEX, 0.6 , (0, 0, 255), 2)
                    robot_state["steering_command"] = "CENTERED"

        cv2.imshow('feed', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        #sleep schedule
        elapsed = time.time() - start_time
        sleep_time = frame_int - elapsed

        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        else:
            await asyncio.sleep(0.001)

    cap.release()
    cv2.destroyAllWindows()
    print("Camera interface closed down successfully.")
    
if __name__ == "__main__":
    try:
        asyncio.run(Vision_Loop())
    except KeyboardInterrupt:
        cap.release()
        cv2.destroyAllWindows()
        print("Forced termination.")