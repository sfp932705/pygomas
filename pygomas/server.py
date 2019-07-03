import asyncio
import time
from dataclasses import dataclass

import aio_msgpack_rpc
from loguru import logger

from spade.container import Container

TCP_COM = 0  # COMMUNICATION (ACCEPTED, CLOSED, REFUSED)
TCP_AGL = 1  # AGENT LIST
TCP_MAP = 2  # MAP: NAME, CHANGES, etc.
TCP_TIME = 3  # TIME: LEFT TIME


@dataclass
class Client(object):
    reader: object
    writer: object
    is_ready: bool


class MyServicer:
    def __init__(self, server):
        self.server = server

    async def get_map(self):
        print("get_map called -> ")
        # logger.success("get_map called -> " + self.server.map_name)
        return self.server.map_name

    async def get_data(self):
        logger.success("get_data called " + str(len(self.server.data)))
        return self.server.data


class RPCServer(object):
    def __init__(self, map_name, port=8002):
        self.map_name = map_name
        self.port = port
        self.server = None
        self.data = dict()
        self.rpcserver = None

        self.container = Container()
        self.loop = self.container.loop

        rpc_server = aio_msgpack_rpc.Server(MyServicer(self))
        self.rpc_coro = asyncio.start_server(rpc_server, "", self.port + 1, loop=self.loop)

    def start(self):
        self.rpcserver = self.loop.create_task(self.rpc_coro)
        logger.info("RPC Render Server started: {}".format(self.rpcserver))

    def update(self, data):
        self.data = data

    def stop(self):
        self.rpcserver.close()


class Server(object):
    def __init__(self, map_name, port=8001):
        self.clients = {}
        self.map_name = map_name
        self.port = port
        self.server = None

        self.data = dict()

        self.container = Container()
        self.loop = self.container.loop

        self.coro = asyncio.start_server(self.accept_client, "", self.port, loop=self.loop)

    def update(self, data):
        self.data = data

    def get_connections(self):
        return self.clients.keys()

    def start(self):
        self.server = self.loop.create_task(self.coro)
        logger.info("Render Server started: {}".format(self.server))

    def stop(self):
        self.server.stop()
        self.loop.run_until_complete(self.server.wait_closed())

    def accept_client(self, client_reader, client_writer):
        logger.info("New Connection")
        task = asyncio.Task(self.handle_client(client_reader, client_writer))
        self.clients[task] = Client(reader=client_reader, writer=client_writer, is_ready=False)

        def client_done(task_):
            del self.clients[task_]
            client_writer.close()
            logger.info("End Connection")

        task.add_done_callback(client_done)

    def is_ready(self, task):
        return self.clients[task].is_ready

    async def handle_client(self, reader, writer):
        task = None
        for k, v in self.clients.items():
            if v.reader == reader and v.writer == writer:
                task = k
                break
        # + ":" + str(self.request)
        logger.info("Preparing Connection to " + str(task))

        try:
            welcome_message = "JGOMAS Render Engine Server v. 0.1.0, {}\n".format(time.asctime()).encode("ASCII")
            writer.write(welcome_message)
            # await writer.drain()
            logger.info("{} (len={})".format(welcome_message, len(welcome_message)))
        except Exception as e:
            logger.error("EXCEPTION IN WELCOME MESSAGE")
            logger.error(str(e))

        while True:
            data = await reader.readline()
            if data is None:
                logger.info("Received no data")
                # exit echo loop and disconnect
                return
            # self.synchronizer.release()
            data = data.decode().rstrip()
            logger.debug("Client says:" + data)
            if "READY" in data:
                logger.info("Server: Connection Accepted")
                self.send_msg_to_render_engine(task, TCP_COM, "Server: Connection Accepted")
                self.send_msg_to_render_engine(task, TCP_MAP, "NAME: " + self.map_name + " ")
                logger.info("Sending: map name: " + self.map_name)

                if "READYv2" in data:
                    self.send_msg_to_render_engine(task, TCP_COM, "READYv2: " + str(self.port + 1) + " ")
                else:
                    self.clients[task] = Client(reader=reader, writer=writer, is_ready=True)

            elif "MAPNAME" in data:
                logger.info("Server: Client requested mapname")
                self.send_msg_to_render_engine(task, TCP_MAP, "NAME: " + self.map_name + " ")
                self.clients[task] = Client(reader, writer, True)

            elif "QUIT" in data:
                logger.info("Server: Client quitted")
                self.send_msg_to_render_engine(task, TCP_COM, "Server: Connection Closed")
                return
            else:
                # Close connection
                logger.info("Socket closed, closing connection.")
                return

    def send_msg_to_render_engine(self, task, msg_type, msg):
        writer = None
        for k, v in self.clients.items():
            if k == task:
                writer = v.writer
                break
        if writer is None:
            logger.info("Connection for {task} not found".format(task=task))
            return
        type_dict = {TCP_COM: "COM", TCP_AGL: "AGL",
                     TCP_MAP: "MAP", TCP_TIME: "TIME"}

        msg_type = type_dict[msg_type] if msg_type in type_dict else "ERR"

        msg_to_send = "{} {}\n".format(msg_type, msg)
        try:
            writer.write(msg_to_send.encode("ASCII"))
        except Exception as e:
            logger.error("EXCEPTION IN SENDMSGTORE: {}".format(e))
