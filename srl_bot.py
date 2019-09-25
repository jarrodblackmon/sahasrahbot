import argparse
import asyncio
import re
import shlex
import time
import json

import aioschedule as schedule
import pydle
import aiohttp

from alttprbot.alttprgen.preset import get_preset
from alttprbot.alttprgen.random import generate_random_game
from alttprbot.alttprgen.weights import weights
from alttprbot.database import srl_races
from alttprbot.util import orm
from config import Config as c


class SrlBot(pydle.Client):
    async def on_connect(self):
        await self.message('NickServ', 'identify ' + c.SRL_PASSWORD)
        await self.join('#speedrunslive')

    # target = channel of the message
    # source = sendering of the message
    # message = the message, duh
    async def on_message(self, target, source, message):
        print('MESSAGE: ' + target + ' - ' + source +
              ' - ' + message)  # dumb debugging message

        # filter messages sent by the bot (we do not want to react to these)
        if source == c.SRL_NICK:
            return

        if (target == '#speedrunslive' and source == 'RaceBot') or (target == 'SahasrahTest' and source == 'synack'):
            p = re.compile("Race initiated for The Legend of Zelda: A Link to the Past Hacks\. Join (#srl-[a-z0-9]{5}) to participate\.")
            result = p.search(message)
            if result:
                await asyncio.sleep(1)
                await self.join(result.group(1))

        if not message[0] == '$':
            return

        split_msg = ['sb'] + shlex.split(message)

        parser = argparse.ArgumentParser()
        parser.add_argument('base', type=str)

        subparsers = parser.add_subparsers(dest="command")

        parser_preset = subparsers.add_parser('$preset')
        parser_preset.add_argument('preset')

        parser_spoiler = subparsers.add_parser('$spoiler')

        parser_random = subparsers.add_parser('$random')
        parser_random.add_argument('weightset', nargs='?', default="weighted")

        parser_join = subparsers.add_parser('$joinroom')
        parser_join.add_argument('channel')

        parser_echo = subparsers.add_parser('$echo')
        parser_echo.add_argument('message')

        args = parser.parse_args(split_msg)
        # print(args)

        if args.command == '$preset' and target.startswith('#srl-'):
            await self.message(target, "Generating game, please wait.")
            srl_id = srl_race_id(target)
            seed, goal_name = await get_preset(args.preset)
            if not seed:
                await self.message(target, "That preset does not exist.")
                return
            goal = f"vt8 randomizer - {goal_name}"
            code = await seed.code()
            await self.message(target, f".setgoal {goal} - {seed.url} - ({'/'.join(code)})")
            await srl_races.insert_srl_race(srl_id, goal)

        if args.command == '$random' and target.startswith('#srl-'):
            await self.message(target, "Generating game, please wait.")
            srl_id = srl_race_id(target)
            seed = await generate_random_game(logic='NoGlitches', weightset=args.weightset, tournament=True)
            code = await seed.code()
            goal = f"vt8 randomizer - random {args.weightset}"
            await self.message(target, f".setgoal {goal} - {seed.url} - ({'/'.join(code)})")
            await srl_races.insert_srl_race(srl_id, goal)

        if args.command == '$spoiler' and target.startswith('#srl-'):
            await self.message(target, "Not yet implemented.  Sorry!")

        if args.command == '$joinroom':
            await self.join(args.channel)

        if args.command == '$echo':
            await self.message(source, args.message)

    # target = you
    # source = sendering of the message
    # message = the message, duh
    async def on_notice(self, target, source, message):
        print('NOTICE: ' + target + ' - ' + source +
              ' - ' + message)  # dumb debugging message

        # do stuff that we want after getting recognized by NickServ
        if message == 'Password accepted - you are now recognized.':
            await asyncio.sleep(1)
            await join_active_races('alttphacks')
            await process_active_races()
            # schedule.every(1).minutes.do(join_active_races, 'alttphacks')
            schedule.every(1).minutes.do(process_active_races)


async def join_active_races(game):
    races = await get_all_races()
    for race in races['races']:
        if race['game']['abbrev'] == game:
            race_id=race['id']
            if not client.in_channel(f'#srl-{race_id}'):
                await client.join(f'#srl-{race_id}')
                print(f'joined #srl-{race_id} on startup')

async def process_active_races():
    print('process active races running')
    active_races = await srl_races.get_srl_races()
    for active_race in active_races:
        race = await get_race(active_race['srl_id'])
        channel_name = f"#srl-{active_race['srl_id']}"
        if not race:
            await srl_races.delete_srl_race(active_race['srl_id'])
        elif not race['state'] == 1:
            if not client.in_channel(channel_name):
                await client.join(channel_name)
            await client.message(channel_name, f".setgoal {active_race['goal']}")
            await srl_races.delete_srl_race(active_race['srl_id'])

async def get_race(raceid):
    return await request_generic(f'http://api.speedrunslive.com/races/{raceid}', returntype='json')

async def get_all_races():
    return await request_generic(f'http://api.speedrunslive.com/races', returntype='json')

def srl_race_id(channel):
    if re.search('^#srl-[a-z0-9]{5}$', channel):
        return channel.partition('-')[-1]

async def request_generic(url, method='get', reqparams=None, data=None, header={}, auth=None, returntype='text'):
    async with aiohttp.ClientSession(auth=None, raise_for_status=True) as session:
        async with session.request(method.upper(), url, params=reqparams, data=data, headers=header, auth=auth) as resp:
            if returntype == 'text':
                return await resp.text()
            elif returntype == 'json':
                return json.loads(await resp.text())
            elif returntype == 'binary':
                return await resp.read()

# the actual scheduler loop 
async def scheduler():
    while True:
        await schedule.run_pending()
        await asyncio.sleep(1)

if __name__ == '__main__':
    client = SrlBot(c.SRL_NICK, realname=c.SRL_NICK)
    loop = asyncio.get_event_loop()
    loop.create_task(orm.create_pool(loop))
    loop.create_task(scheduler())
    client.run('irc.speedrunslive.com')