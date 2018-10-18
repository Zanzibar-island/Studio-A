# Proximity Occupation Sensor
# Remote Client
#
# Server by Daniel Osmond 13197963
# Object Detection by Adam van Zuylen 12895571
#
# 4/08/18
#
# This python script is written to allow for a remote client to collect sensor data and sent it via MQTT to a broker for onward transmission
#
#

#Libraries

#AWS MQTT IoT SDK
import AWSIoTPythonSDK.MQTTLib as AWSIoTPyMQTT

# import openCV and related packages
import cv2
import numpy as np
from picamera.array import PiRGBArray
from picamera import PiCamera
import time

#time libraries
import time
import datetime

#json encoding/decoding libraries
import json
import jsonpickle

#commandline argument parsing
import argparse

#Variable Declarations

#server has requested update if true
pendingUpdate = True
#server has issued some command that needs executing if true
pendingCommand = True
#server has requested a remote shutdown if true
pendingShutdown = False
#current occupation of desk (False if unoccupied, True if occupied)
currentlyOccupied = False
#is there a change to the occupancy that the server needs to be made aware of
pendingOccupancyChange = True

#Declare and set variables for object detection
index = -1
thickness = 4
color = (255, 0, 255)
minObjectSize = 150

# initialise camera and reference to raw camera capture
camera = PiCamera()
camera.resolution = (1920, 1088)
camera.framerate = 1
rawCapture = PiRGBArray(camera)
print("Camera Warming Up")
imageNumber = 1



#Class Definitions

############################################################################
#   Class: Seat                                                            #
#   This class is used to store information about an available desk        #
#                                                                          #
#   Variables                                                              #
#   location: the physical location of the desk (i.e. CB11.08.600)         #
#   status: the occupancy status of the desk. 0 - unoccupied, 1 - occupied #
#   date: the time of the last occupancy status change                     #
############################################################################

class seat:
    def __init__(self, location, status, date):
        self.location = location
        self.status = status
        self.date = date


#Function definitions

###########################################################################
#   Function:dataRX                                                       #
#   This function is used to process incoming messages                    #
#                                                                         #
#   Variables (N.B. client and userdata are unused, pending depreciation) #
#   client : Client that sent the messages                                #
#   userdata: userdata that can be used in the processing of the callback #
#   payload: the main contents of the incoming messages                   #
###########################################################################


def dataRX(client, userdata, message):

    #verbose notification
    if debug:
        print("[NOTICE] MQTT message recieved")

    #Pulls the payload from the message
    payloadJSON = message.payload
    #converts the message from json
    payload = json.loads(payloadJSON)
    #if the payload is a command, execute command
    
    #global variables for control
    global pendingUpdate
    global pendingCommand
    global pendingShutdown


    #Server has remote requested status update of all devices
    if(payload == "update"):
        if debug:
            print("[NOTICE] Server has requested update")
        pendingUpdate = True
        pendingCommand = True
        if debug:
            print(pendingUpdate)
            print(pendingCommand)

    #Server has remote requested shutdown of all devices
    elif(payload == "stop"):
        if debug:
            print("[NOTICE] Server has requested shutdown")
        pendingShutdown = True
        pendingCommand = True

###########################################################################
#   Function:seatMSG                                                      #
#   This function is used to create the payload message with seat info    #
#                                                                         #
#   Outputs                                                               #
#   This function returns a fully json encoded seat type object, with the #
#   seat location, occupancy status, and time of message generation       #
###########################################################################

def seatMSG():
    

    #location and occupancy status
    location = seatLocation
    status = currentlyOccupied
    if status:
        status = "Occupied"
    else:
        status = "Unoccupied"
        
        
    #current datetime in local time
    date = time.asctime(time.localtime())
    #convert variables to a seat type object
    desk = seat(location,status,date)
    #pickle the seat object, so that it is json encodeable
    deskPickle = jsonpickle.encode(desk)
    #json encode the pickled seat
    messageJSON = json.dumps("seat"+deskPickle)

    if debug:
        print("[NOTICE] Seat encoded and pickled")

    #return the json encoded seat from the function
    return(messageJSON)


#Use argparse to take in CLI arguments

cliArgs = argparse.ArgumentParser()

cliArgs.add_argument("-end", action="store", required =True, dest="endpoint", help="AWS IoT Endpoint")
cliArgs.add_argument("-root", action="store", required = True, dest = "rootCA", help="AWS Root CA")
cliArgs.add_argument("-cert", action="store", required=True, dest = "userCert", help ="Device Certificate")
cliArgs.add_argument("-key", action="store", required=True, dest = "privateKey", help ="Device Private Key")
cliArgs.add_argument("-id", action="store", required=True, dest = "clientID", help = "Device Client ID")
cliArgs.add_argument("-top", action="store", dest="topic", default="studio/seating", help ="Topic Channel to Post")
cliArgs.add_argument("-loc", action="store", required= True, dest="loc", help = "Desk Location this Script Applies to")
cliArgs.add_argument("-verbose", action="store_true", dest="debug", help="Enable verbose mode")

args = cliArgs.parse_args()

endpoint = args.endpoint #the endpoint/server that the mqtt connection is made to
rootCA = args.rootCA #AWS's root certificate (Class 3 Public Primary)
userCert = args.userCert
privateKey = args.privateKey
clientID = args.clientID
topic = args.topic
debug = args.debug
seatLocation = args.loc



# AWS MQTT Client Setup

#Default port for auth'ed connection is 8883, 443 for websocket however codebase needs to be changed to implement
port = 8883

#Client Security config
MQTTClient = None
MQTTClient = AWSIoTPyMQTT.AWSIoTMQTTClient(clientID)
MQTTClient.configureEndpoint(endpoint, port)
MQTTClient.configureCredentials(rootCA, privateKey, userCert)

#Client Server Connection Settings
#Reconnect in event of temporary connection failure. (Initial time to wait before attempting to reconnect, maximum time to wait before attempting to reconnect, time for a connection to be considered stable (resets wait time to minimum)) All given in seconds
MQTTClient.configureAutoReconnectBackoffTime(1,32,20)

#Configure queue size in event of connection offline. (size of queue, action to complete when queue full).
#As the server only needs the latest data which will overwrite older data, no need to send older data, risks confusion
MQTTClient.configureOfflinePublishQueueing(1, AWSIoTPyMQTT.DROP_OLDEST)

#Configure rate at which to send queued messages (per second)
MQTTClient.configureDrainingFrequency(2)

#Configure time to wait for disconnect to complete (in seconds)
MQTTClient.configureConnectDisconnectTimeout(10)

#Configure publish, subscribe, unsubscribe operation timeout for QoS 1 service (seconds)
MQTTClient.configureMQTTOperationTimeout(5)

#MQTT CONFIG COMPLETE


#MQTT subscribe to check for incoming commands

#Connect to MQTT service
connectCheck = MQTTClient.connect()

#Verbose connection notifiers
if debug:
    if connectCheck:
        print("[NOTICE] Successfully connected to MQTT")
    else:
        print("[ERROR] Unsuccessful connection to MQTT")

#subscribe to given topic channel
subscribeCheck = MQTTClient.subscribe(topic, 1, dataRX)

#Verbose subscription notifiers
if debug:
    if subscribeCheck:
        print("[NOTICE] Successfully subscribed to %s" %(topic))
    else:
        print("[ERROR] Subscription to %s failed" %(topic))


print("[NOTICE] Started Successfully")
#main loop runs while program not told to shutdown by remote client
while not pendingShutdown:
    # capture frame from camera
    camera.capture(rawCapture, format="bgr", use_video_port=True)
    print("Image Captured")
    #Reset number of detected objects
    numContours = 0
    print('Processing Image...')
    time_last = time.time()
    image = rawCapture.array            
    blur = cv2.GaussianBlur(image, (131,131), 0)
                                                                                                                                                                                                                                                                    
    gray = cv2.cvtColor(blur, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 115, 3)
    _, contours, hierarchy = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    for c in contours:
        area = cv2.contourArea(c)
        #Check if large object
        if area > minObjectSize:
            cv2.drawContours(image, [c], -1, color, 3)
            numContours += 1
            #Find and plot center of object
            M = cv2.moments(c)
            cx = int( M['m10']/M['m00'])
            cy = int( M['m01']/M['m00'])
            cv2.circle(image, (cx,cy), 4, (0,0,255), -1)
          
    timeTaken = round(time.time()-time_last, 4)

    cv2.putText(image, '{}'.format(timeTaken), (100,100), 0, 2.5, (0,255,0), 2, cv2.LINE_AA)
    #Save image file for debugging purposes
    cv2.imwrite('/home/pi/Desktop/frame%s.jpeg' % imageNumber, image)
    print("Number of Objects found:", numContours)
    print('Frame took {} seconds'.format(timeTaken))
    #If objects are found, let the server know!
    if numContours > 1:
        currentlyOccupied = True
        pendingOccupancyChange = True
    else:
        currentlyOccupied = False
        pendingOccupancyChange = True
            
    # clear the stream in preparation for the next frame
    rawCapture.truncate(0)
    imageNumber+=1
    

    print("Command status")
    print(pendingCommand)
    print("update status")
    print(pendingUpdate)
    #if there is a pending update or command, execute command
    if(pendingOccupancyChange or pendingCommand):
        if(pendingShutdown):
            #Here to stop pendingUpdate accidentally eating the shutdown command
            pendingShutdown = True
            pendingOccupancyChange = False
            pendingUpdate = False

        if(pendingOccupancyChange or pendingUpdate):
            #generate payload
            payload = seatMSG()
            #publish update
            publishCheck = MQTTClient.publish(topic, payload, 1)
            #verbose notifications
            if debug:
                if publishCheck:
                    print("[NOTICE] Seat update published to %s successfully" %(topic))
                else:
                    print("[NOTICE] Seat update to %s failed to publish" %(topic))
            
            #reset invoking flags
            pendingOccupancyChange = False
            pendingUpdate = False
            pendingCommand = False
    time.sleep(5)

#pendingShutdown has become true, program will go for halt
#disconnect from MQTT
MQTTClient.disconnect()
#notify user, even if not in verbose mode
print("Shutting Down")
