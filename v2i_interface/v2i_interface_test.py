#!/usr/bin/env python3
# coding: utf-8

# Copyright 2021 eve autonomy inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from datetime import datetime
import json
from socket import AF_INET, IPPROTO_UDP, SOCK_DGRAM, socket
import threading
import time

# https://pysimplegui.readthedocs.io/en/latest/
import PySimpleGUI as sg

import os

import signal
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSDurabilityPolicy, QoSProfile

M_SIZE = 4096

class DummyInfraEcu:
    def __init__(self, address, send_port, recv_port, timeout, buff_size):

        self._send_seq_num = 0
        self._send_address = address
        self._send_port = send_port
        self._send_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)

        self._recv_address = '0.0.0.0'
        self._recv_port = recv_port
        self._buff_size = buff_size
        self._recv_socket = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        self._recv_socket.bind((self._recv_address, self._recv_port))
        self._recv_socket.settimeout(timeout)

    def __del__(self):
        self._send_socket.close()
        self._recv_socket.close()

    def send(self, id, status, detail, reply_array):
        now_time = time.time_ns()
        sec_time = (int)(now_time / 1000 / 1000 / 1000)
        nanosec_time = now_time - (sec_time * 1000 * 1000 * 1000)

        payload = {
            "seq_num": self._send_seq_num,
            "time": {
                "sec": sec_time,
                "nanosec": nanosec_time},
            "id": id,
            "status": status,
            "detail": detail,
            "reply_array": reply_array}

        self._send_socket.sendto(
            json.dumps(payload).encode("utf-8"),
            (self._send_address, self._send_port))
        self._send_seq_num += 1

        return (self._send_seq_num, now_time)

    def recv(self):
        try:
            message, cli_addr = self._recv_socket.recvfrom(self._buff_size)
        except OSError:
            return -1

        now_time = time.time_ns()
        data = json.loads(message)
        recv_seq_num = data["seq_num"]
        packet_time = (data["time"]["sec"] * 1000 *
                       1000 * 1000) + data["time"]["nanosec"]
        request_array = data["request_array"]

        return (recv_seq_num, now_time, packet_time, request_array)


class V2iInterfaceTest(Node):
    def __init__(self):
        super().__init__('v2i_interface')
        global window

        # This node sends to v2i_interface/receive_port,
        #  and receives from v2i_interface/send_port.
        ip_address = self.declare_parameter("ip_address", "127.0.0.1")
        send_port = self.declare_parameter("receive_port", 50001)
        receive_port = self.declare_parameter("send_port", 50000)
        self._ip_address = ip_address.get_parameter_value().string_value
        self._send_port = send_port.get_parameter_value().integer_value
        self._receive_port = receive_port.get_parameter_value().integer_value

        self._th_close = False
        self._dummy = DummyInfraEcu(
            self._ip_address,
            self._send_port,
            self._receive_port,
            10.0,
            M_SIZE)

        output_directory = "/tmp/v2i_interface_test/log/" + \
            datetime.now().strftime('%Y%m%d_%H%M') + "/"
        self._recv_output_filename = output_directory + "recv_data.log"
        self._send_output_filename = output_directory + "send_data.log"

        self._send_count = [[-1, -1, -1], [-1, -1, -1]]

        initial_reply_data = {
            "id": 0, "time": {"sec": 0, "nanosec": 0},
            "status": 0, "packet_time": {"sec": 0, "msec": 0},
            "gpio": 0, "detail": 0,
            "vehicle": {
                "id": 0,
                "request": 0,
                "delay": 0,
                "rssi": 0, },
            "rssi": 0}

        self._reply_array = []
        self._reply_array.append(initial_reply_data.copy())
        self._reply_array.append(initial_reply_data.copy())
        self._reply_array.append(initial_reply_data.copy())
        self._send_flg = False

        sg.theme('Dark Blue 3')

        layout = [
            [sg.Text('Dummy external device')],
            [
                sg.Text('ID:'),
                sg.InputText(
                    '001',
                    size=(
                        3,
                        1),
                    key='-ID0-'),
                sg.Text('GPIO:'),
                sg.InputText(
                    '0',
                    size=(
                        4,
                        1),
                    key='-GPIO0-'),
                sg.Text('Period(ms):'),
                sg.InputText(
                    '-1',
                    size=(
                        4,
                        1),
                    key='-PERIOD0-')],
            [
                sg.Text('ID:'),
                sg.InputText(
                    '002',
                    size=(
                        3,
                        1),
                    key='-ID1-'),
                sg.Text('GPIO:'),
                sg.InputText(
                    '0',
                    size=(
                        4,
                        1),
                    key='-GPIO1-'),
                sg.Text('Period(ms):'),
                sg.InputText(
                    '-1',
                    size=(
                        4,
                        1),
                    key='-PERIOD1-')],
            [
                sg.Text('ID:'),
                sg.InputText(
                    '003',
                    size=(
                        3,
                        1),
                    key='-ID2-'),
                sg.Text('GPIO:'),
                sg.InputText(
                    '0',
                    size=(
                        4,
                        1),
                    key='-GPIO2-'),
                sg.Text('Period(ms):'),
                sg.InputText(
                    '-1',
                    size=(
                        4,
                        1),
                    key='-PERIOD2-')],
            [sg.Button('Start ', key='-BUTTON1-', size=(7, 1),),
             sg.Button('Stop', key='-BUTTON2-', size=(7, 1),)],
            [sg.Output(size=(680, 100))],
        ]

        window = sg.Window(
            title='dummy_infrastructure', size=(700, 700)).Layout(layout)
        self.run()

    def __del__(self):
        del self._dummy

    def main_loop(self):
        self._window_refresh_interval_ms = 100
        self._base_time = time.time()
        while True:
            if(self._th_close):
                break
            data_flg = False
            reply_array = []
            if(self._send_flg):
                for i in range(len(self._send_count[0])):
                    if(self._send_count[0][i] > 0):
                        if(self._send_count[1][i] < self._window_refresh_interval_ms):
                            self._send_count[1][i] = self._send_count[0][i]
                            reply_array.append(self._reply_array[i])
                            data_flg = True
                        else:
                            self._send_count[1][i] -= self._window_refresh_interval_ms
            if (data_flg):
                self._dummy.send(1, 1, 1, reply_array)
                print("send write")
                self._fp_send.write('{}, '.format(time.time_ns()))
                self._fp_send.write(', '.join('{}'.format(x)
                                              for x in reply_array))
                self._fp_send.write('\n')
            window.Refresh()
            next_sleep = (
                (((self._base_time - time.time()) * 1000) %
                 self._window_refresh_interval_ms) or self._window_refresh_interval_ms) / 1000
            time.sleep(next_sleep)

    def recv_from_v2i_interface(self):
        while True:
            if(self._th_close):
                break

            ret = self._dummy.recv()
            if(ret != -1):
                print("recv write")
                self._fp_recv.write(', '.join('{}'.format(x) for x in ret))
                self._fp_recv.write('\n')
            time.sleep(0.1)
            pass

    def run(self):
        global window
        os.makedirs(os.path.dirname(self._recv_output_filename), exist_ok=True)
        os.makedirs(os.path.dirname(self._send_output_filename), exist_ok=True)

        self._fp_recv = open(self._recv_output_filename, 'a')
        th_infra_ecu = threading.Thread(target=self.recv_from_v2i_interface)
        th_infra_ecu.start()

        self._fp_send = open(self._send_output_filename, 'a')
        th_main = threading.Thread(target=self.main_loop)
        th_main.start()

        while True:
            event, values = window.read()
            if event is None:
                break
            if event == sg.WIN_CLOSED:
                break
            if event == '-BUTTON1-':
                for i in range(len(self._send_count[0])):
                    self._send_count[0][i] = int(
                        values["-PERIOD" + str(i) + "-"])
                    self._send_count[1][i] = int(
                        values["-PERIOD" + str(i) + "-"])
                    self._reply_array[i]["id"] = int(
                        values["-ID" + str(i) + "-"])
                    self._reply_array[i]["gpio"] = int(
                        values["-GPIO" + str(i) + "-"], 0)
                self._send_flg = True
                window['-BUTTON1-'].update("Change")
            if event == '-BUTTON2-':
                self._send_flg = False
                window['-BUTTON1-'].update("Start ")

        self._th_close = True
        window.close()
        th_infra_ecu.join()
        th_main.join()
        self._fp_recv.close()
        self._fp_send.close()

def shutdown(signal, frame):
    node.fin()
    node.destroy_node()
    rclpy.shutdown()

def main(args=None):
    global node
    signal.signal(signal.SIGINT, shutdown)

    rclpy.init(args=args)

    node = V2iInterfaceTest()

    rclpy.spin(node)


if __name__ == "__main__":
    main()
