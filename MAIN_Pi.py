#MAIN Pi
import asyncio
from CV_Pi import Vision_Loop, robot_state
    
async def main_robot():

    await asyncio.gather(
        Vision_Loop(),          # Task 1: Updates steering_command
        #Gemini_Voice_Loop(),    # Task 2: Updates speech/intents
        #uart_loop()             # Task 3: Sends commands to ESP32 wires
    )

if __name__ == "__main__":
    try:
        asyncio.run(main_robot())
    except KeyboardInterrupt:
        print("Robot brain shut down cleanly.")