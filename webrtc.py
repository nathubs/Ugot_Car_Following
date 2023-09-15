# UgotWebRtc.py
import asyncio
import json
import re
import threading
from queue import Queue
import cv2
import requests
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceCandidate, VideoStreamTrack, RTCConfiguration
from aiortc.contrib.media import MediaBlackhole
from aiortc.contrib.signaling import BYE
from aiortc.sdp import candidate_from_sdp
class UgotWebRtc:
    class VideoSink(VideoStreamTrack):
        def __init__(self, track):
            super().__init__()
            self.track = track
            self.task = None
            self.frameQueue = Queue()
            self.__on_delivery_frame__ = None
            self.on_new_frame = None
        async def recv(self):
            frame = await self.track.recv()
            if self.frameQueue.empty() and self.__on_delivery_frame__ is not None:
                self.frameQueue.put(frame)
            return frame
        async def __blackhole_consume__(self):
            while True:
                try:
                    await self.recv()
                except Exception as e:
                    print(e)
        def set_on_delivery_frame(self, callback):
            self.__on_delivery_frame__ = callback
        def __delivery_frame__(self):
            while not self.task.done():
                frame = self.frameQueue.get()
                if frame is not None and self.__on_delivery_frame__ is not None:
                    try:
                        img = frame.to_ndarray(format="bgr24")
                        self.__on_delivery_frame__(img, frame)
                    except:
                        pass
        async def start(self):
            self.task = asyncio.ensure_future(self.__blackhole_consume__())
            threading.Thread(target=self.__delivery_frame__, daemon=True).start()
        async def stop(self):
            if self.task is not None:
                self.task.cancel()
    class UgotSignaling:
        class OnlineUser:
            def __init__(self, name: str, id: int, online: bool):
                self.name = name
                self.id = id
                self.online = online
            @staticmethod
            def parseLine(line: str):
                ret = re.search("(?P<name>[^,]+),(?P<id>\d+),(?P<online>.*)", line)
                if ret:
                    return UgotWebRtc.UgotSignaling.OnlineUser(ret.group('name'), int(ret.group('id')),
                                                               True if ret.group('online') == '1' else False)
                else:
                    return None
            def __str__(self) -> str:
                return f'{self.name}, {self.id}, {"online" if self.online else "offline"}'
        def __init__(self, addr: str, port: int = 10000, username: str = 'python@UgotWebRtc'):
            self.addr = addr
            self.port = port
            self.username = username
            self.onlineUser = []
            self.localId = -1
            self.remoteId = -1
            self.recvQueue = Queue()
            self.__request_url__ = f'http://{self.addr}:{self.port}'
        def connected(self):
            return self.localId != -1
        async def connect(self):
            response = requests.get(f'{self.__request_url__}/sign_in?{self.username}')
            if response.ok:
                self.localId = int(response.headers.get('Pragma'))
                reponseData = response.text
                for line in reponseData.splitlines():
                    user = self.OnlineUser.parseLine(line)
                    if user is not None:
                        self.onlineUser.append(user)
                        print(f'useronlinestatechange {user}')
                self.remoteId = list(filter(lambda user: user.name.startswith('user@UGOT_'), self.onlineUser))[0].id   
                print(f'localId={self.localId}, remoteId={self.remoteId}')
                threading.Thread(target=self.__receive__, daemon=True).start()
            else:
                raise RuntimeError(response.reason)
        async def close(self):
            if self.localId == -1:
                return
            response = requests.get(f'{self.__request_url__}/sign_out?peer_id={self.localId}')
            if response.ok:
                pass
            else:
                raise RuntimeError(response.reason)
        async def receive(self):
            if self.localId == -1:
                return None
            while self.recvQueue.empty():
                await asyncio.sleep(0.01)
            pragmaId, text = self.recvQueue.get()
            if pragmaId is None or text is None:
                return None
            if pragmaId == self.localId:
                targetUser = self.OnlineUser.parseLine(text)
                if targetUser is not None:
                    existUser = list(filter(lambda user: user.id == targetUser.id, self.onlineUser))
                    if len(existUser) > 0:
                        for user in existUser:
                            if user in self.onlineUser:
                                self.onlineUser.remove(user)
                    if targetUser.online:
                        self.onlineUser.append(targetUser)
                return targetUser
            else:
                if pragmaId != self.remoteId:
                    return None
                if 'BYE' == text:
                    return BYE
                msg = json.loads(text)
                if msg.get('type', None) is None and msg.get('candidate', None) is not None:
                    msg['type'] = 'candidate'
                if msg['type'] == 'answer':
                    return RTCSessionDescription(msg.get('sdp'), 'answer')
                elif msg['type'] == 'candidate':
                    iceCandidate = candidate_from_sdp(msg.get('candidate').split(":", 1)[1])
                    iceCandidate.sdpMid = msg.get('sdpMid')
                    iceCandidate.sdpMLineIndex = int(msg.get('sdpMLineIndex'))
                    return iceCandidate
            return None
        def __receive__(self):
            while self.localId != -1:
                response = requests.get(f'{self.__request_url__}/wait?peer_id={self.localId}', timeout=None)
                if response.ok:
                    pragmaId = int(response.headers.get('Pragma'))
                    self.recvQueue.put((pragmaId, response.text))
        async def send(self, data: str):
            if self.localId == -1 or self.remoteId == -1:
                return
            response = requests.post(f'{self.__request_url__}/message?peer_id={self.localId}&to={self.remoteId}',
                                     headers={'Content-Type': 'text/plain'},
                                     data=data)
            if response.ok:
                pass
            else:
                raise RuntimeError(response.reason)
    def __init__(self, addr: str, port: int = 10000, username: str = 'python@UgotWebRtc'):
        self.signaling = UgotWebRtc.UgotSignaling(addr, port, username)
        self.pc = RTCPeerConnection(RTCConfiguration([]))
        self.videoSink = None
        self.loop = None
        self.__on_delivery_frame__ = None
    def set_on_delivery_frame(self, callback):
        self.__on_delivery_frame__ = callback
    async def __runImpl__(self):
        await self.signaling.connect()
        self.pc.addTransceiver('video', 'recvonly')
        @self.pc.on('track')
        def on_track(track):
            print(f'on_track {track.kind} {track.id}')
            if track.kind == 'video':
                self.videoSink = self.VideoSink(track)
                self.videoSink.set_on_delivery_frame(self.__on_delivery_frame__)
        @self.pc.on('signalingstatechange')
        def signalingstatechange():
            print(f'signalingstatechange {self.pc.signalingState}')
            pass
        @self.pc.on('icegatheringstatechange')
        def icegatheringstatechange():
            print(f'icegatheringstatechange {self.pc.iceGatheringState}')
            pass
        @self.pc.on('iceconnectionstatechange')
        def iceconnectionstatechange():
            print(f'iceconnectionstatechange {self.pc.iceConnectionState}')
            pass
        @self.pc.on('connectionstatechange')
        def connectionstatechange():
            print(f'connectionstatechange {self.pc.connectionState}')
            pass
        offer = await self.pc.createOffer()
        # print(offer)
        await self.pc.setLocalDescription(offer)
        await self.signaling.send(json.dumps({'type': 'offer', 'sdp': offer.sdp}))
        while self.signaling.connected():
            obj = await self.signaling.receive()
            if obj is None:
                continue
            if isinstance(obj, RTCSessionDescription):
                await self.pc.setRemoteDescription(obj)
                if self.videoSink is not None:
                    await self.videoSink.start()
            elif isinstance(obj, RTCIceCandidate):
                await self.pc.addIceCandidate(obj)
            elif isinstance(obj, UgotWebRtc.UgotSignaling.OnlineUser):
                print(f'useronlinestatechange {obj}')
            elif obj is BYE:
                print("Exiting")
                break
    def start(self):
        def __rtc_thread__():
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.__runImpl__())
            except KeyboardInterrupt:
                pass
            finally:
                if self.videoSink is not None:
                    loop.run_until_complete(self.videoSink.stop())
                loop.run_until_complete(self.signaling.close())
                loop.run_until_complete(self.pc.close())
        threading.Thread(target=__rtc_thread__, daemon=True).start()
    def stop(self):
        self.localId = -1
        self.remoteId = -1
if __name__ == '__main__':
    import time
    uexplore_wlan_addr = '192.168.50.45'
    ugotWebrtc = UgotWebRtc(uexplore_wlan_addr)
    @ugotWebrtc.set_on_delivery_frame
    def on_new_frame(frame_img, frame_av):
        cv2.imshow("frame", frame_img)
        cv2.waitKey(1)
    ugotWebrtc.start()
    time.sleep(30)
    ugotWebrtc.stop()