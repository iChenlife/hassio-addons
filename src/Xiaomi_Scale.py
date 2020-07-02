#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function
import argparse
import binascii
import time
import os
import sys
import subprocess
from bluepy import btle
from bluepy.btle import Scanner, BTLEDisconnectError, BTLEManagementError, DefaultDelegate
import paho.mqtt.publish as publish
from datetime import datetime
import json

import Xiaomi_Scale_Body_Metrics



# First Log msg
sys.stdout.write(' \n')
sys.stdout.write('-------------------------------------\n')
sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Starting Xiaomi mi Scale...\n")

# Configuraiton...
# Trying To Load Config From options.json (HA Add-On)
try:
    with open('/data/options.json') as json_file:
        sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Loading Config From Add-On Options...\n")
        data = json.load(json_file)
        MISCALE_MAC = data["MISCALE_MAC"]
        MQTT_USERNAME = None if(data["MQTT_USERNAME"] == "") else data["MQTT_USERNAME"]
        MQTT_PASSWORD = None if(data["MQTT_PASSWORD"] == "") else data["MQTT_PASSWORD"]
        MQTT_HOST = data["MQTT_HOST"]
        MQTT_PORT = int(data["MQTT_PORT"])
        MQTT_PREFIX = data["MQTT_PREFIX"]
        TIME_INTERVAL = int(data["TIME_INTERVAL"])
        MQTT_DISCOVERY = data["MQTT_DISCOVERY"]
        MQTT_DISCOVERY_PREFIX = data["MQTT_DISCOVERY_PREFIX"]
        HCI_DEV = data["HCI_DEV"][-1]

        # User Variables...
        USER1_GT = int(data["USER1_GT"])
        USER1_SEX = data["USER1_SEX"]
        USER1_NAME = data["USER1_NAME"]
        USER1_HEIGHT = int(data["USER1_HEIGHT"])
        USER1_DOB = data["USER1_DOB"]

        USER2_LT = int(data["USER2_LT"])
        USER2_SEX = data["USER2_SEX"]
        USER2_NAME = data["USER2_NAME"]
        USER2_HEIGHT = int(data["USER2_HEIGHT"])
        USER2_DOB = data["USER2_DOB"]

        USER3_SEX = data["USER3_SEX"]
        USER3_NAME = data["USER3_NAME"]
        USER3_HEIGHT = int(data["USER3_HEIGHT"])
        USER3_DOB = data["USER3_DOB"]
        sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Config Loaded...\n")

# Failed to open options.json, Loading Config From Environment (Not HA Add-On)
except FileNotFoundError:
    pass
    sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Loading Config From OS Environment...\n")
    MISCALE_MAC = os.getenv('MISCALE_MAC', '')
    MQTT_USERNAME = os.getenv('MQTT_USERNAME', 'username')
    MQTT_PASSWORD = os.getenv('MQTT_PASSWORD', None)
    MQTT_HOST = os.getenv('MQTT_HOST', '127.0.0.1')
    MQTT_PORT = int(os.getenv('MQTT_PORT', 1883))
    MQTT_PREFIX = os.getenv('MQTT_PREFIX', 'miscale')
    TIME_INTERVAL = int(os.getenv('TIME_INTERVAL', 30))
    MQTT_DISCOVERY = os.getenv('MQTT_DISCOVERY',True)
    MQTT_DISCOVERY_PREFIX = os.getenv('MQTT_DISCOVERY_PREFIX','homeassistant')
    HCI_DEV = os.getenv('HCI_DEV', 'hci0')[-1]

    # User Variables...
    USER1_GT = int(os.getenv('USER1_GT', '70')) # If the weight is greater than this number, we'll assume that we're weighing User #1
    USER1_SEX = os.getenv('USER1_SEX', 'male')
    USER1_NAME = os.getenv('USER1_NAME', 'David') # Name of the user
    USER1_HEIGHT = int(os.getenv('USER1_HEIGHT', '175')) # Height (in cm) of the user
    USER1_DOB = os.getenv('USER1_DOB', '1988-09-30') # DOB (in yyyy-mm-dd format)

    USER2_LT = int(os.getenv('USER2_LT', '55')) # If the weight is less than this number, we'll assume that we're weighing User #2
    USER2_SEX = os.getenv('USER2_SEX', 'female')
    USER2_NAME = os.getenv('USER2_NAME', 'Joanne') # Name of the user
    USER2_HEIGHT = int(os.getenv('USER2_HEIGHT', '155')) # Height (in cm) of the user
    USER2_DOB = os.getenv('USER2_DOB', '1988-10-20') # DOB (in yyyy-mm-dd format)

    USER3_SEX = os.getenv('USER3_SEX', 'male')
    USER3_NAME = os.getenv('USER3_NAME', 'Unknown User') # Name of the user
    USER3_HEIGHT = int(os.getenv('USER3_HEIGHT', '175')) # Height (in cm) of the user
    USER3_DOB = os.getenv('USER3_DOB', '1988-01-01') # DOB (in yyyy-mm-dd format)
    sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Config Loaded...\n")

OLD_MEASURE = ''

def discovery():
    for MQTTUser in (USER1_NAME,USER2_NAME,USER3_NAME):
        message = '{"name": "' + MQTTUser + ' Weight",'
        message+= '"state_topic": "miScale/' + MQTTUser + '/weight","value_template": "{{ value_json.Weight }}","unit_of_measurement": "kg",'
        message+= '"json_attributes_topic": "miScale/' + MQTTUser + '/weight","icon": "mdi:scale-bathroom"}'
        publish.single(
                        MQTT_DISCOVERY_PREFIX + '/sensor/' + MQTT_PREFIX + '/' + MQTTUser + '/config',
                        message,
                        retain=True,
                        hostname=MQTT_HOST,
                        port=MQTT_PORT,
                        auth={'username':MQTT_USERNAME, 'password':MQTT_PASSWORD}
                    )
    sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Discovery Completed...\n")


class ScanProcessor():
    def GetAge(self, d1):
        d1 = datetime.strptime(d1, "%Y-%m-%d")
        d2 = datetime.strptime(datetime.today().strftime('%Y-%m-%d'),'%Y-%m-%d')
        return abs((d2 - d1).days)/365

    def __init__(self):
        DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        global OLD_MEASURE
        if dev.addr == MISCALE_MAC.lower() and isNewDev:
            for (sdid, desc, data) in dev.getScanData():
                ### Xiaomi V1 Scale ###
                if data.startswith('1d18') and sdid == 22:
                    measunit = data[4:6]
                    measured = int((data[8:10] + data[6:8]), 16) * 0.01
                    unit = ''
                    if measunit.startswith(('03', 'b3')): unit = 'lbs'
                    if measunit.startswith(('12', 'b2')): unit = 'jin'
                    if measunit.startswith(('22', 'a2')): unit = 'kg' ; measured = measured / 2
                    if unit:
                        if OLD_MEASURE != round(measured, 2):
                            self._publish(round(measured, 2), unit, str(datetime.today().strftime('%Y-%m-%d-%H:%M:%S')), "", "")
                            OLD_MEASURE = round(measured, 2)

                ### Xiaomi V2 Scale ###
                if data.startswith('1b18') and sdid == 22:
                    data2 = bytes.fromhex(data[4:])
                    ctrlByte1 = data2[1]
                    isStabilized = ctrlByte1 & (1<<5)
                    hasImpedance = ctrlByte1 & (1<<1)

                    measunit = data[4:6]
                    measured = int((data[28:30] + data[26:28]), 16) * 0.01
                    unit = ''
                    if measunit == "03": unit = 'lbs'
                    if measunit == "02": unit = 'kg' ; measured = measured / 2
                    #mitdatetime = datetime.strptime(str(int((data[10:12] + data[8:10]), 16)) + " " + str(int((data[12:14]), 16)) +" "+ str(int((data[14:16]), 16)) +" "+ str(int((data[16:18]), 16)) +" "+ str(int((data[18:20]), 16)) +" "+ str(int((data[20:22]), 16)), "%Y %m %d %H %M %S")
                    miimpedance = str(int((data[24:26] + data[22:24]), 16))
                    if unit and isStabilized:
                        if OLD_MEASURE != round(measured, 2) + int(miimpedance):
                            self._publish(round(measured, 2), unit, str(datetime.today().strftime('%Y-%m-%d-%H:%M:%S')), hasImpedance, miimpedance)
                            OLD_MEASURE = round(measured, 2) + int(miimpedance)


    def _publish(self, weight, unit, mitdatetime, hasImpedance, miimpedance):
        if int(weight) > USER1_GT:
            user = USER1_NAME
            height = USER1_HEIGHT
            age = self.GetAge(USER1_DOB)
            sex = USER1_SEX
        elif int(weight) < USER2_LT:
            user = USER2_NAME
            height = USER2_HEIGHT
            age = self.GetAge(USER2_DOB)
            sex = USER2_SEX
        else:
            user = USER3_NAME
            height = USER3_HEIGHT
            age = self.GetAge(USER3_DOB)
            sex = USER3_SEX
        lib = Xiaomi_Scale_Body_Metrics.bodyMetrics(weight, height, age, sex, 0)
        message = '{'
        message += '"Weight":"' + "{:.2f}".format(weight) + '"'
        message += ',"BMI":"' + "{:.2f}".format(lib.getBMI()) + '"'
        message += ',"Basal Metabolism":"' + "{:.2f}".format(lib.getBMR()) + '"'
        message += ',"Visceral Fat":"' + "{:.2f}".format(lib.getVisceralFat()) + '"'

        if hasImpedance:
            lib = Xiaomi_Scale_Body_Metrics.bodyMetrics(weight, height, age, sex, int(miimpedance))
            bodyscale = ['Obese', 'Overweight', 'Thick-set', 'Lack-exerscise', 'Balanced', 'Balanced-muscular', 'Skinny', 'Balanced-skinny', 'Skinny-muscular']
            message += ',"Lean Body Mass":"' + "{:.2f}".format(lib.getLBMCoefficient()) + '"'
            message += ',"Body Fat":"' + "{:.2f}".format(lib.getFatPercentage()) + '"'
            message += ',"Water":"' + "{:.2f}".format(lib.getWaterPercentage()) + '"'
            message += ',"Bone Mass":"' + "{:.2f}".format(lib.getBoneMass()) + '"'
            message += ',"Muscle Mass":"' + "{:.2f}".format(lib.getMuscleMass()) + '"'
            message += ',"Protein":"' + "{:.2f}".format(lib.getProteinPercentage()) + '"'
            message += ',"Body Type":"' + str(bodyscale[lib.getBodyType()]) + '"'
            message += ',"Metabolic Age":"' + "{:.0f}".format(lib.getMetabolicAge()) + '"'

        message += ',"TimeStamp":"' + mitdatetime + '"'
        message += '}'
        try:
            sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Publishing data to topic {MQTT_PREFIX + '/' + user + '/weight'}: {message}\n")
            publish.single(
                MQTT_PREFIX + '/' + user + '/weight',
                message,
                # qos=1, #Removed qos=1 as incorrect connection details will result in the client waiting for ack from broker
                retain=True,
                hostname=MQTT_HOST,
                port=MQTT_PORT,
                auth={'username':MQTT_USERNAME, 'password':MQTT_PASSWORD}
            )
            sys.stdout.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Data Published ...\n")
        except Exception as error:
            sys.stderr.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Could not publish to MQTT: {error}\n")
            raise

def main():
    if MQTT_DISCOVERY:
        discovery()
    BluetoothFailCounter = 0
    while True:
        try:
            scanner = btle.Scanner(HCI_DEV).withDelegate(ScanProcessor())
            scanner.scan(5) # Adding passive=True to try and fix issues on RPi devices
        except BTLEDisconnectError as error:
            sys.stderr.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - btle disconnected: {error}\n")
            pass
        except BTLEManagementError as error:
            sys.stderr.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Bluetooth connection error: {error}\n")
            if BluetoothFailCounter >= 4:
                sys.stderr.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - 5+ Bluetooth connection errors. Resetting Bluetooth...\n")
                cmd = 'hciconfig hci0 reset'
                ps = subprocess.Popen(cmd, shell=True)
                time.sleep(30)
                BluetoothFailCounter = 0
            else:
                BluetoothFailCounter+=1
            pass
        except Exception as error:
            sys.stderr.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - Error while running the script: {error}\n")
            pass
        else:
            BluetoothFailCounter = 0
        time.sleep(TIME_INTERVAL)

if __name__ == "__main__":
    main()
