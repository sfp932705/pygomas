import asyncio
import datetime
import json
import time
import math

import msgpack
from loguru import logger

import spade
from spade.agent import Agent
from spade.behaviour import OneShotBehaviour, PeriodicBehaviour, CyclicBehaviour, TimeoutBehaviour
from spade.message import Message
from spade.template import Template

from . import MIN_HEALTH
from .config import *
from .stats import GameStatistic
from .mobile import Mobile
from .vector import Vector3D
from .pack import PACK_NAME, PACK_NONE, PACK_OBJPACK, PACK_MEDICPACK, PACK_AMMOPACK
from .agent import AbstractAgent, LONG_RECEIVE_WAIT
from .config import Config, MSGPACK_AGENTS, MSGPACK_PACKS, MSGPACK_NAME, MSGPACK_TYPE, MSGPACK_TEAM, MSGPACK_HEALTH, \
    MSGPACK_AMMO, MSGPACK_IS_CARRYING, MSGPACK_POSITION, MSGPACK_VELOCITY, MSGPACK_HEADING
from .service import Service
from .server import Server, TCP_AGL, TCP_COM, RPCServer
from .bditroop import CLASS_SOLDIER
from .objpack import ObjectivePack
from .map import TerrainMap
from .sight import Sight

MILLISECONDS_IN_A_SECOND: int = 1000

DEFAULT_PACK_QTY: int = 20

ARG_PLAYERS: int = 0
ARG_MAP_NAME: int = 1
ARG_FPS: int = 2
ARG_MATCH_TIME: int = 3
ARG_MAP_PATH: int = 4

WIDTH: int = 3


class MicroAgent:

    def __init__(self, ):
        self.jid = ""
        self.team = TEAM_NONE
        self.locate = Mobile()
        self.is_carrying_objective = False
        self.is_shooting = False
        self.health = 0
        self.ammo = 0
        self.type = 0

    def __str__(self):
        return "<{} Team({}) Health({}) Ammo({}) Obj({})>".format(self.jid, self.team, self.health, self.ammo,
                                                                  self.is_carrying_objective)


class DinObject:

    def __str__(self):
        return "DO({},{})".format(PACK_NAME[self.type], self.position)

    def __init__(self):
        self.position = Vector3D()
        self.type = PACK_NONE
        self.team = TEAM_NONE
        self.is_taken = False
        self.owner = 0
        self.jid = None


class Manager(AbstractAgent, Agent):

    def __init__(self,
                 name="cmanager@localhost",
                 passwd="secret",
                 players=10,
                 fps=0.033,
                 match_time=380,
                 map_name="map_01",
                 map_path=None,
                 service_jid="cservice@localhost",
                 service_passwd="secret",
                 port=8001):

        AbstractAgent.__init__(self, name, service_jid=service_jid)
        Agent.__init__(self, name, passwd)

        self.game_statistic = GameStatistic()
        self.max_total_agents = players
        self.fps = fps
        self.match_time = match_time
        self.map_name = str(map_name)
        self.port = port
        self.config = Config(data_path=map_path)
        self.number_of_agents = 0
        self.agents = {}
        self.match_init = 0
        self.domain = name.split('@')[1]
        self.objective_agent = None
        self.service_agent = Service(jid=self.service_jid, password=service_passwd)
        self.render_server = Server(map_name=self.map_name, port=self.port)
        self.rpc_server = RPCServer(map_name=self.map_name, port=self.port + 1)
        self.din_objects = dict()
        self.map = TerrainMap()

    def _in_coroutine(self):
        try:
            return asyncio.get_event_loop() == self.loop
        except RuntimeError:  # pragma: no cover
            return False

    def stop(self):
        del self.render_server
        self.render_server = None
        if self._in_coroutine():
            coro1 = self.objective_agent.stop()
            coro2 = self.service_agent.stop()
            coro3 = super().stop()
            coro = asyncio.gather(coro1, coro2, coro3)

        else:
            self.objective_agent.stop().result()
            self.service_agent.stop().result()
            coro = super().stop()

        return coro

    async def setup(self):
        class InitBehaviour(OneShotBehaviour):
            async def run(self):
                logger.success("Manager (Expected Agents): {}".format(self.agent.max_total_agents))

                # for i in range(1, self.agent.max_total_agents + 1):
                while self.agent.number_of_agents < self.agent.max_total_agents:
                    msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if msg:
                        content = json.loads(msg.body)

                        name = content[NAME]
                        type_ = content[TYPE]
                        team = content[TEAM]

                        self.agent.agents[name] = MicroAgent()

                        self.agent.agents[name].jid = name
                        self.agent.agents[name].type = int(type_)
                        self.agent.agents[name].team = int(team)
                        self.agent.agents[name].health = 100

                        logger.success("Manager: [" + name + "] is Ready!")
                        self.agent.number_of_agents += 1

                logger.success("Manager (Accepted Agents): " + str(self.agent.number_of_agents))
                for agent in self.agent.agents.values():
                    msg = Message()
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
                    msg.to = agent.jid
                    msg.body = json.dumps({MAP: self.agent.map_name})
                    await self.send(msg)
                    logger.success("Manager: Sending notification to fight to: " + agent.jid)

                await self.agent.inform_objectives(self)
                self.agent.match_init = time.time()

                # Behaviour to check if all alied troops are alive
                self.agent.launch_check_allied_health()

        logger.success("pyGOMAS v. 0.1 (c) GTI-IA 2005 - 2019 (DSIC / UPV)")
        logger.success(spade.__version__)
        # manager_future = super().start(auto_register=auto_register)

        # Manager notify its services in a different way
        coro = self.service_agent.start(auto_register=True)
        await coro

        self.register_service(MANAGEMENT_SERVICE)

        self.render_server.start()
        self.rpc_server.start()

        self.map.load_map(self.map_name, self.config)

        # Behaviour to listen to data (position, health?, an so on) from troop agents
        self.launch_data_from_troop_listener_behaviour()

        # Behaviour to handle Shot messages
        self.launch_shoot_responder_behaviour()

        # Behaviour to handle Pack Management: Creation and Destruction
        self.launch_pack_management_responder_behaviour()

        # Behaviour to inform all agents that game has finished by time
        self.launch_game_timeout_inform_behaviour()

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_INIT)
        self.add_behaviour(InitBehaviour(), template)

        await self.create_objectives()  # We need to do this when online

        # Behaviour to refresh all render engines connected
        self.launch_render_engine_inform_behaviour()

    # Behaviour to refresh all render engines connected
    def launch_render_engine_inform_behaviour(self):

        class InformRenderEngineBehaviour(PeriodicBehaviour):
            async def run(self):
                try:
                    if self.agent.render_server and self.agent.render_server.get_connections() is not {}:
                        # v1
                        for task in self.agent.render_server.get_connections():
                            msg = self.__prepare_message_v1()
                            self.agent.render_server.send_msg_to_render_engine(task, TCP_AGL, msg)
                            # logger.info("msg to render engine")
                        # v2
                    msg = self.__prepare_message_v2()
                    self.agent.rpc_server.update(msg)
                    # logger.info("msg to render engine")
                except Exception:
                    pass

            def __prepare_message_v2(self):
                msg = {
                    MSGPACK_AGENTS: [{
                        MSGPACK_NAME: agent.jid.split("@")[0],
                        MSGPACK_TYPE: agent.type,
                        MSGPACK_TEAM: agent.team,
                        MSGPACK_HEALTH: agent.health,
                        MSGPACK_AMMO: agent.ammo,
                        MSGPACK_IS_CARRYING: agent.is_carrying_objective,
                        MSGPACK_POSITION: (agent.locate.position.x, agent.locate.position.y, agent.locate.position.z),
                        MSGPACK_VELOCITY: (agent.locate.velocity.x, agent.locate.velocity.y, agent.locate.velocity.z),
                        MSGPACK_HEADING: (agent.locate.heading.x, agent.locate.heading.y, agent.locate.heading.z),
                    } for agent in self.agent.agents.values()],
                    MSGPACK_PACKS: [{
                        MSGPACK_NAME: din_object.render_id,
                        MSGPACK_TYPE: din_object.type,
                        MSGPACK_POSITION: (din_object.position.x, din_object.position.y, din_object.position.z)}
                        for din_object in self.agent.din_objects.values() if not din_object.is_taken]}

                return msgpack.packb(msg)

            def __prepare_message_v1(self):
                msg = "" + str(self.agent.number_of_agents) + " "
                for agent in self.agent.agents.values():
                    msg += agent.jid.split("@")[0] + " "
                    msg += str(agent.type) + " "
                    msg += str(agent.team) + " "

                    msg += str(agent.health) + " "
                    msg += str(agent.ammo) + " "
                    if agent.is_carrying_objective:
                        msg += str(1)
                    else:
                        msg += str(0)

                    msg += " (" + str(agent.locate.position.x) + ", "
                    msg += str(agent.locate.position.y) + ", "
                    msg += str(agent.locate.position.z) + ") "

                    msg += "(" + str(agent.locate.velocity.x) + ", "
                    msg += str(agent.locate.velocity.y) + ", "
                    msg += str(agent.locate.velocity.z) + ") "

                    msg += "(" + str(agent.locate.heading.x) + ", "
                    msg += str(agent.locate.heading.y) + ", "
                    msg += str(agent.locate.heading.z) + ") "
                num_din_objects = sum([not din.is_taken for din in self.agent.din_objects.values()])
                msg += str(num_din_objects) + " "
                for din_object in self.agent.din_objects.values():
                    if not din_object.is_taken:
                        msg += str(din_object.render_id) + " "
                        msg += str(din_object.type) + " "
                        msg += " (" + str(din_object.position.x) + ", "
                        msg += str(din_object.position.y) + ", "
                        msg += str(din_object.position.z) + ") "
                return msg

        self.add_behaviour(InformRenderEngineBehaviour(self.fps))

    # Behaviour to listen to data (position, health?, an so on) from troop agents
    def launch_data_from_troop_listener_behaviour(self):
        class DataFromTroopBehaviour(CyclicBehaviour):
            async def run(self):
                try:
                    # buffer = defaultdict(list)
                    # while self.mailbox_size() > 0:
                    #    msg = await self.receive(timeout=0)
                    #    content = json.loads(msg.body)
                    #    buffer[content[NAME]].append(content)
                    msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                    if self.mailbox_size() > self.agent.max_total_agents + 1:
                        logger.error("TOO MUCH PENDING MSG: {}".format(self.mailbox_size()))
                    # for id_agent, msgs in buffer.items():
                    if msg:
                        #    for content in msgs:
                        content = json.loads(msg.body)
                        id_agent = content[NAME]
                        self.agent.agents[id_agent].locate.position.x = int(content[X])
                        self.agent.agents[id_agent].locate.position.y = int(content[Y])
                        self.agent.agents[id_agent].locate.position.z = int(content[Z])

                        self.agent.agents[id_agent].locate.velocity.x = float(content[VEL_X])
                        self.agent.agents[id_agent].locate.velocity.y = float(content[VEL_Y])
                        self.agent.agents[id_agent].locate.velocity.z = float(content[VEL_Z])

                        self.agent.agents[id_agent].locate.heading.x = float(content[HEAD_X])
                        self.agent.agents[id_agent].locate.heading.y = float(content[HEAD_Y])
                        self.agent.agents[id_agent].locate.heading.z = float(content[HEAD_Z])

                        self.agent.agents[id_agent].health = int(content[HEALTH])
                        self.agent.agents[id_agent].ammo = int(content[AMMO])

                        packs = await self.agent.check_objects_at_step(id_agent, behaviour=self)
                        fov_objects = self.agent.look(id_agent)
                        content = {PACKS: packs, FOV: fov_objects}
                        msg = Message(to=id_agent)
                        msg.set_metadata(PERFORMATIVE, PERFORMATIVE_DATA)
                        msg.body = json.dumps(content)

                        await self.send(msg)
                        if self.agent.check_game_finished(id_agent):
                            await self.agent.inform_game_finished("ALLIED", self)
                            logger.success("\n\nManager:  GAME FINISHED!! Winner Team: ALLIED! (Target Returned)\n")
                except Exception as e:
                    logger.warning("Exception at DataFromTroopBehaviour: {}".format(e))

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_DATA)

        self.add_behaviour(DataFromTroopBehaviour(), template)

    # Behaviour to handle Shot messages
    def launch_shoot_responder_behaviour(self):
        class ShootResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(timeout=LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)
                    shooter_id = content[NAME]
                    aim = int(content[AIM])
                    shots = int(content[SHOTS])
                    victim_pos = Vector3D(x=content[X], y=content[Y], z=content[Z])
                    try:
                        shooter = self.agent.agents[shooter_id]
                    except KeyError:
                        return

                    victim = self.agent.shoot(shooter_id, victim_pos)
                    self.agent.game_statistic.shoot(victim, shooter.team)

                    if victim is None:
                        return

                    damage = 3 if shooter.type == CLASS_SOLDIER else 2
                    damage *= shots
                    victim.health -= damage
                    logger.info("Victim hit: {}".format(victim))

                    if victim.health <= 0:
                        victim.health = 0
                        logger.info("Agent {} died.".format(victim.jid))

                        if victim.is_carrying_objective:
                            victim.is_carrying_objective = False
                            logger.info("Agent {} lost the ObjectivePack.".format(victim.jid))

                            for din_object in self.agent.din_objects.values():

                                if din_object.type == PACK_OBJPACK:
                                    din_object.is_taken = False
                                    din_object.owner = 0
                                    msg_pack = Message(to=str(din_object.jid))
                                    msg_pack.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK_LOST)
                                    din_object.position.x = victim.locate.position.x
                                    din_object.position.y = victim.locate.position.y
                                    din_object.position.z = victim.locate.position.z
                                    msg_pack.body = json.dumps({
                                        X: victim.locate.position.x,
                                        Y: victim.locate.position.y,
                                        Z: victim.locate.position.z})
                                    await self.send(msg_pack)

                                    # Statistics
                                    self.agent.game_statistic.objective_lost(
                                        victim.team)
                                    break

                    msg_shot = Message(to=victim.jid)
                    msg_shot.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOOT)
                    msg_shot.body = json.dumps({DEC_HEALTH: damage})
                    await self.send(msg_shot)

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_SHOOT)
        self.add_behaviour(ShootResponderBehaviour(), template)

    # Behaviour to handle Pack Management: Creation and Destruction
    def launch_pack_management_responder_behaviour(self):

        class PackManagementResponderBehaviour(CyclicBehaviour):
            async def run(self):
                msg = await self.receive(LONG_RECEIVE_WAIT)
                if msg:
                    content = json.loads(msg.body)

                    id_ = content[NAME]
                    action = content[ACTION]

                    if action == DESTROY:
                        self.agent.game_statistic.pack_destroyed(self.agent.din_objects[id_])

                        try:
                            del self.agent.din_objects[id_]
                            logger.info("Pack removed")
                        except KeyError:
                            logger.info("Pack {} cannot be erased".format(id_))
                        return

                    if action == CREATE:
                        type_ = int(content[TYPE])
                        team = int(content[TEAM])

                        x = float(content[X])
                        y = float(content[Y])
                        z = float(content[Z])

                        din_object = DinObject()
                        din_object.jid = msg.sender
                        din_object.type = type_
                        if din_object.type == PACK_OBJPACK:
                            din_object.render_id = 1
                        else:
                            din_object.render_id = abs(
                                hash(din_object.jid)) % 1024
                        din_object.team = team
                        din_object.position.x = x
                        din_object.position.y = y
                        din_object.position.z = z

                        self.agent.din_objects[din_object.jid] = din_object
                        logger.info("Added DinObject {}".format(din_object))

                        self.agent.game_statistic.pack_created(din_object, team)

                    else:
                        logger.warning("Action not identified: {}".format(action))
                        return

        template = Template()
        template.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK)
        self.add_behaviour(PackManagementResponderBehaviour(), template)

    # Behaviour to inform all agents that game has finished by time
    def launch_game_timeout_inform_behaviour(self):
        class GameTimeoutInformBehaviour(TimeoutBehaviour):
            async def run(self):
                logger.success("\n\nManager:  GAME FINISHED!! Winner Team: AXIS! (Time Expired)\n")
                await self.agent.inform_game_finished("AXIS!", self)

        timeout = datetime.datetime.now() + datetime.timedelta(seconds=self.match_time)
        self.add_behaviour(GameTimeoutInformBehaviour(start_at=timeout))

    # Behaviour to inform all agents that game has finished because all allied troops died
    def launch_check_allied_health(self):
        class CheckAlliedHealthBehaviour(PeriodicBehaviour):
            async def run(self):
                allied_alive = False
                for agent in self.agent.agents.values():
                    if agent.team == TEAM_AXIS:
                        continue
                    if agent.health > 0:
                        allied_alive = True
                        break
                if not allied_alive:
                    logger.success("\n\nManager:  GAME FINISHED!! Winner Team: AXIS!\n")
                    await self.agent.inform_game_finished("AXIS!", self)

        self.add_behaviour(CheckAlliedHealthBehaviour(20 * self.fps))

    async def check_objects_at_step(self, id_agent, behaviour):

        if len(self.din_objects) <= 0:
            return

        if self.agents[id_agent].health <= 0:
            return

        xmin = self.agents[id_agent].locate.position.x - WIDTH
        zmin = self.agents[id_agent].locate.position.z - WIDTH
        xmax = self.agents[id_agent].locate.position.x + WIDTH
        zmax = self.agents[id_agent].locate.position.z + WIDTH

        packs = []

        keys = list(self.din_objects.keys())
        for key in keys:
            if key not in self.din_objects:
                continue
            din_object = self.din_objects[key]
            if din_object.type == PACK_MEDICPACK and self.agents[id_agent].health >= 100:
                continue
            if din_object.type == PACK_AMMOPACK and self.agents[id_agent].ammo >= 100:
                continue
            if din_object.type == PACK_OBJPACK and din_object.is_taken and din_object.owner != 0:
                continue

            if xmin <= din_object.position.x <= xmax and zmin <= din_object.position.z <= zmax:
                # Agent has stepped on pack
                id_ = din_object.jid
                type_ = din_object.type
                owner = str(din_object.jid)
                content = None

                team = self.agents[id_agent].team
                self.game_statistic.pack_taken(din_object, team)

                if din_object.type == PACK_MEDICPACK:
                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(self.agents[id_agent].jid + ": got a medic pack " + str(din_object.jid))
                        content = {TYPE: type_, QTY: quantity}

                    except KeyError:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_AMMOPACK:
                    quantity = DEFAULT_PACK_QTY
                    try:
                        del self.din_objects[id_]
                        logger.info(self.agents[id_agent].jid + ": got an ammo pack " + str(din_object.jid))
                        content = {TYPE: type_, QTY: quantity}
                    except KeyError:
                        logger.error("Could not delete the din object {}".format(id_))

                elif din_object.type == PACK_OBJPACK:
                    if team == TEAM_ALLIED:
                        logger.info("{}: got the objective pack ".format(self.agents[id_agent].jid))
                        din_object.is_taken = True
                        din_object.owner = id_agent
                        din_object.position.x, din_object.position.y, din_object.position.z = 0.0, 0.0, 0.0
                        self.agents[id_agent].is_carrying_objective = True
                        content = {TYPE: type_, QTY: 0, TEAM: TEAM_ALLIED}

                    elif team == TEAM_AXIS:
                        if din_object.is_taken:
                            logger.info(f"{self.agents[id_agent].jid}: returned the objective pack {din_object.jid}")
                            din_object.is_taken = False
                            din_object.owner = 0
                            din_object.position.x = self.map.get_target_x()
                            din_object.position.y = self.map.get_target_y()
                            din_object.position.z = self.map.get_target_z()
                            content = {TYPE: type_, QTY: 0, TEAM: TEAM_AXIS}

                # // Send a destroy/taken msg to pack and an inform msg to agent
                if content:
                    content = json.dumps(content)
                    msg = Message(to=owner)
                    msg.set_metadata(PERFORMATIVE, PERFORMATIVE_PACK_TAKEN)
                    msg.body = content
                    await behaviour.send(msg)
                    packs.append(content)
        return packs

    def look(self, name):
        fov_objects = self.get_objects_in_field_of_view(name)
        content = []
        for fov_object in fov_objects:
            obj = {
                TEAM: fov_object.team,
                TYPE: fov_object.type,
                ANGLE: fov_object.angle,
                DISTANCE: fov_object.distance,
                HEALTH: fov_object.health,
                X: fov_object.position.x,
                Y: fov_object.position.y,
                Z: fov_object.position.z
            }
            content.append(obj)
        return content

    def get_objects_in_field_of_view(self, id_agent):

        objects_in_sight = list()
        agent = None

        for a in self.agents.values():
            if a.jid == id_agent:
                agent = a
                break

        if agent is None:
            return objects_in_sight

        dot_angle = float(agent.locate.angle)

        # am I watching agents?
        for a in self.agents.values():
            if a.jid == id_agent:
                continue
            if a.health <= MIN_HEALTH:  # WARNING, we may be interested in seeing dead agents
                continue

            v = Vector3D(v=a.locate.position)
            v.sub(agent.locate.position)

            distance = v.length()

            # check distance
            # get distance to the closest wall
            distance_terrain = self.intersect(agent.locate.position, v)  # a.locate.heading)

            # check distance
            if distance < agent.locate.view_radius and distance < distance_terrain:

                # check angle
                angle = agent.locate.heading.dot(v)
                try:
                    angle /= agent.locate.heading.length() * v.length()
                except ZeroDivisionError:
                    pass

                if angle >= 0:
                    angle = min(1, angle)
                    angle = math.acos(angle)
                    if angle <= dot_angle:
                        s = Sight()
                        s.distance = distance
                        s.m_id = a.jid
                        s.position = a.locate.position
                        s.team = a.team
                        s.type = a.type
                        s.angle = angle
                        s.health = a.health
                        objects_in_sight.append(s)

        # am I watching objects?
        if len(self.din_objects) > 0:

            for din_object in self.din_objects.values():

                v = Vector3D(v=din_object.position)
                v.sub(agent.locate.position)

                distance = v.length()

                # check distance
                # get distance to the closest wall
                distance_terrain = self.intersect(agent.locate.position, v)  # a.locate.heading)

                if distance < agent.locate.view_radius and distance < distance_terrain:

                    angle = agent.locate.heading.dot(v)
                    angle /= (agent.locate.heading.length() * v.length())
                    if angle >= 0:
                        angle = min(1, angle)
                        angle = math.acos(angle)
                        if angle <= dot_angle:
                            s = Sight()
                            s.distance = distance
                            s.m_id = din_object.jid
                            s.position = din_object.position
                            s.team = din_object.team
                            s.type = din_object.type
                            s.angle = angle
                            s.health = -1
                            objects_in_sight.append(s)

        return objects_in_sight

    def shoot(self, id_agent, victim_position):
        """
        Agent with id id_agent shoots
        :param id_agent: agent who shoots
        :param victim_position: the coordinates of the victim to be shot
        :return: agent shot or None
        """
        victim = None
        try:
            agent = self.agents[id_agent]
        except KeyError:
            return None

        # agents
        for a in self.agents.values():
            if a.jid == id_agent:
                continue
            if a.health <= 0:
                continue
            absx = abs(victim_position.x - a.locate.position.x)
            absz = abs(victim_position.z - a.locate.position.z)
            if (absx < PRECISION_X) and (absz < PRECISION_Z):
                victim = a
                v = Vector3D(v=victim.locate.position)
                v.sub(agent.locate.position)
                min_distance = v.length()
                break

        if victim is not None:
            a = Mobile()
            a.position = agent.locate.position
            a.destination = victim.locate.position
            a.calculate_new_orientation(a.destination)
            distance_terrain = self.intersect(a.position, a.heading, min_distance)
            # logger.info("distanceTerrain: " + str(distance_terrain))
            if distance_terrain != 0.0 and distance_terrain < min_distance:
                victim = None

        return victim

    def intersect(self, origin, vector, distance=1e10):
        """
        :param origin:
        :param vector:
        :param distance:
        :return: 0.0 if it does not intersect
        """

        try:

            if vector.length() == 0:
                return 0.0

            step = Vector3D(v=vector)
            step.normalize()
            inc = 0
            sgn = 1.0
            e = 0.0

            if abs(step.x) > abs(step.z):

                if step.z < 0:
                    sgn = -1

                step.x /= abs(step.x)
                step.z /= abs(step.x)
            else:

                if step.x < 0:
                    sgn = -1

                inc = 1
                step.x /= abs(step.z)
                step.z /= abs(step.z)

            error = Vector3D(x=0, y=0, z=0)
            point = Vector3D(v=origin)

            while True:

                if inc == 0:

                    if e + abs(step.z) + 0.5 >= 1:
                        point.z += sgn
                        e -= 1

                    e += abs(step.z)
                    point.x += step.x
                else:

                    if e + abs(step.x) + 0.5 >= 1:
                        point.x += sgn
                        e -= 1

                    e += abs(step.x)
                    point.z += step.z

                if not self.map.can_walk(int(math.floor(point.x)), int(math.floor(point.z))):
                    return error.length()

                if point.x < 0 or point.y < 0 or point.z < 0:
                    break
                if point.x >= (self.map.get_size_x()) or point.z >= (self.map.get_size_z()):
                    break
                error.add(step)
                if error.length() > distance:
                    return error.length()
        except Exception as e:
            logger.error("INTERSECT FAILED: (origin: {}) (vector: {}): {}".format(origin, vector, e))

        return 0.0

    def check_game_finished(self, id_agent):
        if self.agents[id_agent].team == TEAM_AXIS:
            return False
        if not self.agents[id_agent].is_carrying_objective:
            return False

        if self.map.allied_base.init.x < self.agents[id_agent].locate.position.x < self.map.allied_base.end.x and \
                self.map.allied_base.init.z < self.agents[id_agent].locate.position.z < self.map.allied_base.end.z:
            return True
        return False

    async def create_objectives(self):

        jid = "objectivepack@" + self.domain
        self.objective_agent = ObjectivePack(name=jid, passwd="secret",
                                             manager_jid=str(self.jid),
                                             x=self.map.get_target_x(),
                                             z=self.map.get_target_z(), team=TEAM_NONE)
        await self.objective_agent.start()

    async def inform_objectives(self, behaviour):

        msg = Message()
        msg.set_metadata(PERFORMATIVE, PERFORMATIVE_OBJECTIVE)
        content = {X: self.map.get_target_x(),
                   Y: self.map.get_target_y(),
                   Z: self.map.get_target_z()}
        msg.body = json.dumps(content)
        for agent in self.agents.values():
            msg.to = agent.jid
            logger.info("Sending objective to {}: {}".format(agent.jid, msg))
            await behaviour.send(msg)
        logger.info("Manager: Sending Objective notification to agents")

    async def inform_game_finished(self, winner_team, behaviour):

        for agent in self.agents.values():
            msg = Message()
            msg.set_metadata(PERFORMATIVE, PERFORMATIVE_GAME)
            msg.body = "GAME FINISHED!! Winner Team: " + str(winner_team)
            msg.to = agent.jid
            await behaviour.send(msg)
        for st in self.render_server.get_connections():
            try:
                st.send_msg_to_render_engine(TCP_COM, "FINISH " + " GAME FINISHED!! Winner Team: " + str(winner_team))
            except:
                pass

        self.print_statistics(winner_team)

        await self.stop()

    def print_statistics(self, winner_team):

        allied_alive_players = 0
        axis_alive_players = 0
        allied_health = 0
        axis_health = 0

        self.game_statistic.match_duration = time.time() * MILLISECONDS_IN_A_SECOND
        self.game_statistic.match_duration -= self.match_init

        for agent in self.agents.values():
            if agent.team == TEAM_ALLIED:
                allied_health += agent.health
                if agent.health > 0:
                    allied_alive_players = allied_alive_players + 1
            else:
                axis_health += agent.health
                if agent.health > 0:
                    axis_alive_players = axis_alive_players + 1

        self.game_statistic.calculate_data(
            allied_alive_players, axis_alive_players, allied_health, axis_health)

        try:
            fw = open("PGOMAS_Statistics.txt", 'w+')

            fw.write(self.game_statistic.__str__(winner_team))

            fw.close()

        except Exception as e:
            logger.error("COULD NOT WRITE STATISTICS TO FILE: {}".format(e))
