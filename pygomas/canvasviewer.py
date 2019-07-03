#!/usr/bin/env python
# -*- coding: UTF8 -*-
import asyncio
import datetime
import math
import argparse
import socket
import sys
import os
import traceback
import copy

import aio_msgpack_rpc

import contextlib

with contextlib.redirect_stdout(None):
    import pygame
    from pygame import gfxdraw

from .config import MSGPACK_AGENTS, MSGPACK_NAME, MSGPACK_TYPE, MSGPACK_TEAM, MSGPACK_HEALTH, MSGPACK_AMMO, \
    MSGPACK_IS_CARRYING, MSGPACK_POSITION, MSGPACK_HEADING, MSGPACK_PACKS

rpc_port = 18002

objective_x = -1
objective_y = -1
allied_base = None
axis_base = None
graph = {}
stdscr = None
pad = None
f = None
agents = {}
dins = {}
factor = 2
screen = None
font = None
maps_path = None

iteration = 0

tile_size = 24
horizontal_tiles = 32
vertical_tiles = 32

map_width = tile_size * horizontal_tiles
map_height = tile_size * vertical_tiles

xdesp = 0
ydesp = 0

'''def agl_parse(data):
    global allied_base
    global axis_base
    global objective_x
    global objective_y
    global agents
    global dins

    dins = {}
    # f.write("\nAGL_PARSE\n")
    agl = data.split()
    nagents = int(agl[1])
    agl = agl[2:]
    separator = nagents * 15
    # f.write("NAGENTS = %s\n" % (str(nagents)))
    agent_data = agl[:separator]
    din_data = agl[separator:]
    # f.write("AGENT_DATA:" + str(agent_data))
    for i in range(nagents):
        agents[agent_data[0]] = {"type": agent_data[1], "team": agent_data[2], "health": agent_data[3],
                                 "ammo": agent_data[4], "carrying": agent_data[5], "posx": agent_data[6].strip(
                "(,)"), "posy": agent_data[7].strip("(,)"), "posz": agent_data[8].strip("(,)"),
                                 "angx": agent_data[12].strip("(,)"), "angy": agent_data[13].strip("(,)"),
                                 "angz": agent_data[14].strip("(,)")}
        # f.write("AGENT " + str(agents[agent_data[0]]))
        agent_data = agent_data[15:]

    # f.write("DIN_DATA:" + str(din_data))
    ndin = int(din_data[0])
    # f.write("NDIN = %s\n" % (str(ndin)))
    din_data = din_data[1:]
    for din in range(ndin):
        dins[din_data[0]] = {"type": din_data[1], "posx": din_data[2].strip("(,)"), "posy": din_data[3].strip("(,)"),
                             "posz": din_data[4].strip("(,)")}
        # f.write("DIN " + str(dins[din_data[0]]))
        din_data = din_data[5:]
'''


def msgpack_parse(data):
    global agents
    global dins
    if len(data) == 0:
        return
    for agent_data in data[MSGPACK_AGENTS]:
        agents[str(agent_data[MSGPACK_NAME])] = {
            "type": agent_data[MSGPACK_TYPE],
            "team": agent_data[MSGPACK_TEAM],
            "health": agent_data[MSGPACK_HEALTH],
            "ammo": agent_data[MSGPACK_AMMO],
            "carrying": agent_data[MSGPACK_IS_CARRYING],
            "posx": agent_data[MSGPACK_POSITION][0],
            "posy": agent_data[MSGPACK_POSITION][1],
            "posz": agent_data[MSGPACK_POSITION][2],
            "angx": agent_data[MSGPACK_HEADING][0],
            "angy": agent_data[MSGPACK_HEADING][1],
            "angz": agent_data[MSGPACK_HEADING][2]
        }
    for din_data in data[MSGPACK_PACKS]:
        dins[din_data[MSGPACK_NAME]] = {
            "type": din_data[MSGPACK_TYPE],
            "posx": din_data[MSGPACK_POSITION][0],
            "posy": din_data[MSGPACK_POSITION][1],
            "posz": din_data[MSGPACK_POSITION][2],
        }


def draw2():
    global agents
    global factor
    global xdesp
    global ydesp
    global tile_size
    global iteration
    global screen
    global font

    events = pygame.event.get()
    for event in events:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_LEFT:
                xdesp += tile_size
            if event.key == pygame.K_RIGHT:
                xdesp -= tile_size
            if event.key == pygame.K_DOWN:
                ydesp -= tile_size
            if event.key == pygame.K_UP:
                ydesp += tile_size
            if event.key == pygame.K_x:
                tile_size += 2
            if event.key == pygame.K_z:
                tile_size -= 2

    # Clear screen
    color_background = (0, 0, 0)
    pygame.draw.rect(screen, color_background, (0, 0, map_width, map_height))

    # Draw Map
    color_wall = (100, 100, 100)
    for y in range(0, len(list(graph.items()))):
        for x in range(0, 32):
            try:
                if list(graph.items())[y][1][x] == '*':
                    pygame.draw.rect(screen, color_wall,
                                     (x * tile_size + xdesp, y * tile_size + ydesp, tile_size, tile_size))
            except:
                pass

    # Draw bases
    if allied_base is not None:
        color = (255, 0, 0)
        xpos = int(allied_base[0]) * tile_size + xdesp
        ypos = int(allied_base[1]) * tile_size + ydesp
        xwidth = int(allied_base[2]) * tile_size - xpos + tile_size + xdesp
        ywidth = int(allied_base[3]) * tile_size - ypos + tile_size + ydesp

        pygame.draw.rect(screen, color, (xpos, ypos, xwidth, ywidth))

    if axis_base is not None:
        color = (0, 0, 255)
        xpos = int(axis_base[0]) * tile_size + xdesp
        ypos = int(axis_base[1]) * tile_size + ydesp
        xwidth = int(axis_base[2]) * tile_size - xpos + tile_size + xdesp
        ywidth = int(axis_base[3]) * tile_size - ypos + tile_size + ydesp

        pygame.draw.rect(screen, color, (xpos, ypos, xwidth, ywidth))

    # Draw items
    for i in range(0, len(list(dins.items()))):
        posx = int(float(list(dins.items())[i][1]['posx']) * (tile_size / 8.0)) + xdesp
        posy = int(float(list(dins.items())[i][1]['posz']) * (tile_size / 8.0)) + ydesp

        item_type = {
            "1001": "M",
            "1002": "A",
            "1003": "F"
        }.get(list(dins.items())[i][1]["type"], "X")

        color = {
            "1001": (255, 255, 255),
            "1002": (255, 255, 255),
            "1003": (255, 255, 0)
        }.get(list(dins.items())[i][1]["type"], "X")

        pygame.draw.circle(screen, color, [posx, posy], 6)
        text = font.render(item_type, True, (0, 0, 0))
        screen.blit(text, (posx - text.get_width() // 2, posy - text.get_height() // 2))

    # Draw units
    for i in list(agents.items()):
        health = float(i[1]['health'])

        if float(health) > 0:

            carrying = i[1]['carrying']

            agent_type = {
                "0": "X",
                "1": "*",
                "2": "+",
                "3": "Y",
                "4": "^"
            }.get(i[1]['type'], "X")

            team = {
                "100": (255, 100, 100),
                "200": (100, 100, 255)
            }.get(i[1]['team'], (255, 255, 0))

            team_aplha = {
                "100": (255, 100, 100, 100),
                "200": (100, 100, 255, 100)
            }.get(i[1]['team'], (255, 255, 0, 255))

            ammo = float(i[1]['ammo'])

            posx = int(float(i[1]['posx']) * tile_size / 8.0) + xdesp
            posy = int(float(i[1]['posz']) * tile_size / 8.0) + ydesp

            # calcula direccion
            angx = float(i[1]['angx'])
            angy = float(i[1]['angz'])

            if angx == 0:
                div = 1000
            else:
                div = angy / angx

            if angy >= 0 and angx >= 0:  # q1
                angle = math.atan(div) * (180 / math.pi)
            elif angy >= 0 and angx <= 0:  # q2
                angle = math.atan(div) * (180 / math.pi) + 180
            elif angy <= 0 and angx <= 0:  # q3
                angle = math.atan(div) * (180 / math.pi) + 180
            else:  # q4
                angle = math.atan(div) * (180 / math.pi) + 360

            # imprime ficha
            pygame.draw.circle(screen, team, [posx, posy], 8)
            # imprime identificador
            text = font.render(i[0], True, (255, 255, 255))
            screen.blit(text, (posx - text.get_width() // 2 + 15, posy - text.get_height() // 2 - 15))
            # imprime vida
            pygame.gfxdraw.aacircle(screen, posx, posy, 10, (255, 0, 0))
            pygame.gfxdraw.aacircle(screen, posx, posy, 9, (255, 0, 0))
            pygame.gfxdraw.arc(screen, posx, posy, 10, 0, int(health * 3.6) - 1, (0, 255, 0))
            pygame.gfxdraw.arc(screen, posx, posy, 9, 0, int(health * 3.6) - 1, (0, 255, 0))
            # imprime municion
            if ammo >= 1:
                pygame.gfxdraw.arc(screen, posx, posy, 6, 0, int(ammo * 3.6) - 1, (255, 255, 255))
                pygame.gfxdraw.arc(screen, posx, posy, 7, 0, int(ammo * 3.6) - 1, (255, 255, 255))

            # lleva la bandera
            if carrying == '1':
                pygame.draw.circle(screen, (255, 255, 0), [posx, posy], 5)

            # imprime cono de vision
            for j in range(0, int(48 * (tile_size / 8)), 1):
                pygame.gfxdraw.arc(screen, posx, posy, j, int(-45 + angle), int(45 + angle), team_aplha)

            # imprime funcion
            text = font.render(agent_type, True, (0, 0, 0))
            screen.blit(text, (posx - text.get_width() // 2, posy - text.get_height() // 2))

    pygame.display.flip()
    iteration += 1

    agents_json = {}
    for i in list(agents.items()):
        agents_json[i[0]] = i[1]

    items_json = {}
    for i in list(dins.items()):
        items_json[i[0]] = i[1]

    json_data = {
        "agents": agents_json,
        "items": items_json
    }


def loadMap(map_name):
    global allied_base
    global axis_base
    global objective_x
    global objective_y
    global maps_path

    if maps_path is not None:
        path = f"{maps_path}{os.sep}{map_name}{os.sep}{map_name}"
    else:
        this_dir, _ = os.path.split(__file__)
        path = f"{this_dir}{os.sep}maps{os.sep}{map_name}{os.sep}{map_name}"

    mapf = open(f"{path}.txt", "r")
    cost = open(f"{path}_cost.txt", "r")

    for line in mapf.readlines():
        if "pGomas_OBJECTIVE" in line:
            l = line.split()
            objective_x = copy.copy(int(l[1]))
            objective_y = copy.copy(int(l[2]))
            # f.write("OBJECTIVE:" + str(objective_x) + " " + str(objective_y))
        elif "pGomas_SPAWN_ALLIED" in line:
            l = line.split()
            l.pop(0)
            allied_base = copy.copy(l)
            # f.write("ALLIED_BASE:" + str(l))
        elif "pGomas_SPAWN_AXIS" in line:
            l = line.split()
            l.pop(0)
            axis_base = copy.copy(l)
    mapf.close()
    # f.write("MAPF LOADED\n")

    y = 0
    for line in cost.readlines():
        graph[y] = line.strip("\r\n")
        y += 1
    cost.close()
    # print "GRAPH",str(graph)
    # f.write(str(graph))


def main(address="localhost", port=8001, maps=None):
    global f
    global screen
    global font
    global maps_path
    global rpc_port

    # Main
    maps_path = maps
    f = open("/tmp/tv.log", "w")
    # f.write("LOG\n")

    # Init pygame
    pygame.init()
    font = pygame.font.SysFont("ttf-font-awesome", 12)

    # Set the height and width of the screen
    size = [map_width, map_height]
    screen = pygame.display.set_mode(size)

    # Loop until the user clicks the close button.
    done = False
    clock = pygame.time.Clock()

    try:
        # Init socket
        # f.write("ADDRESS: %s\n" % address)
        # f.write("PORT: %s\n" % (str(port)))
        s = None
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if s:
            # time.sleep(1)
            s.connect((address, port))
            rfile = s.makefile('r', -1)
            wfile = s.makefile('w', 20)
            # f.write(f"SOCKET OPEN {str(s)}\n")
            data = rfile.readline()
            # f.write(f"Server sent: {data}\n")

            wfile.write("READYv2\n")
            wfile.close()

            data = ""
            data = rfile.readline()
            print("GOT DATA", data)
            assert "COM" in data[0:5]
            assert "Accepted" in data

            data = rfile.readline()
            assert "MAP" in data[0:5]

            data = rfile.readline()
            assert "COM" in data[0:5]
            assert "READYv2" in data
            rpc_port = int(data.split()[2])
            print("GOT READYv2 with port " + str(rpc_port))

            asyncio.get_event_loop().run_until_complete(main_loop(address, rpc_port))

            print("Finished main_loop")

        s.close()
    except Exception as e:
        print("Exception", str(e))
        print('-' * 60)
        traceback.print_exc(file=sys.stdout)
        print('-' * 60)

    finally:
        pygame.quit()
        f.close()


async def main_loop(address, port):
    in_loop = True
    try:
        client = aio_msgpack_rpc.Client(*await asyncio.open_connection(address, port))
        print("Got RPC client", client)
        mapname = await client.call("get_map")
        print("Got RPC mapname", mapname)
        loadMap(mapname)

        while in_loop:
            t1 = datetime.datetime.now()
            data = await client.call("get_data")
            msgpack_parse(data)
            draw2()
            t2 = datetime.datetime.now()
            wait = (t2 - t1).seconds
            if wait < 0.033:
                await asyncio.sleep(0.033 - wait)
    except Exception as e:
        print("Async Exception", str(e))
        print('-' * 60)
        traceback.print_exc(file=sys.stdout)
        print('-' * 60)

        '''
        data = ""
        data = rfile.readline()
        # f.write(f"Server sent: {data}\n")
        if "COM" in data[0:5]:
            if "Accepted" in data:
                pass
            elif "Closed" in data:
                in_loop = False
        elif "MAP" in data[0:5]:
            # f.write(f'MAP MESSAGE: {data}\n')
            p = data.split()
            mapname = p[2]
            # f.write(f"MAPNAME: {mapname}\n")
            loadMap(mapname)
        elif "AGL" in data[0:5]:
            # f.write("\nAGL\n")
            # import datetime
            # print("{}: Received msg".format(datetime.datetime.now()))
            # agl_parse(data)
            unpacker = msgpack.Unpacker(rfile, raw=False)
            for unpacked in unpacker:
                msgpack_parse(unpacked)
        elif "TIM" in data[0:5]:
            pass
        elif "ERR" in data[0:5]:
            pass
        else:
            # Unknown message type
            pass
        '''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip', default="localhost", help="Manager's address to connect the render")
    parser.add_argument('--port', default=8001, help="Manager's port to connect the render")
    parser.add_argument('--maps', default=None, help="The path to your custom maps directory")

    args = parser.parse_args()
    main(args.ip, args.port, args.maps)
    sys.exit(0)
