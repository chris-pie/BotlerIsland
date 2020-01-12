from datetime import datetime, timedelta
from collections import defaultdict, deque
import pickle
import discord as dc
from discord.ext import tasks, commands

def callback(): # Lambdas can't be pickled, but named functions can.
    return {'usrlog': None, 'msglog': None, 'star_wars': None}

class Singleton(object):
    instance = None
    def __new__(cls, *args, **kwargs):
        if cls.instance is None:
            cls.instance = super().__new__(cls)
        return cls.instance


class GuildConfig(Singleton):
    def __init__(self, bot, fname):
        StarWarsPunisher.bot = bot
        self.bot = bot
        self.fname = fname
        self.punishers = {}
        self.load()

    def load(self):
        try:
            with open(self.fname, 'rb') as config_file:
                self.mod_channels = pickle.load(config_file)
        except (OSError, EOFError):
            self.mod_channels = defaultdict(callback, {})
            self.save()

    def save(self):
        for guild_id, punisher in self.punishers.items():
            self.mod_channels[guild_id]['star wars'] = punisher.dump()
        with open(self.fname, 'wb') as config_file:
            pickle.dump(self.mod_channels, config_file)

    async def log(self, guild, log, *args, **kwargs):
        await self.bot.get_channel(
            self.mod_channels[guild.id][log]
            ).send(*args, **kwargs)

    def getlog(self, guild, log):
        return self.mod_channels[guild.id][log]

    def setlog(self, ctx, log):
        try:
            self.mod_channels[ctx.guild.id][log] = ctx.channel.id
        except KeyError:
            raise ValueError(f'Invalid log channel type {log}')
        self.save()

    def set_containment(self, ctx):
        guild_id = ctx.guild.id
        star_wars = self.mod_channels[guild_id]['star wars']
        if star_wars is None:
            self.punishers[guild_id] = StarWarsPunisher(guild_id)
            self.save()
        elif guild_id not in self.punishers:
            self.punishers[guild_id] = StarWarsPunisher(
                guild_id, star_wars['banlist'], star_wars['lastcall']
                )
        self.punishers[guild_id].monitor(ctx)

    def detect_star_wars(self, msg):
        if msg.guild.id not in self.punishers:
            return False
        return self.punishers[msg.guild.id].detect(msg)

    async def punish_star_wars(self, msg):
        return await self.punishers[msg.guild.id].punish(msg)


triggers = (
    'star wars', 'starwars', 'star war', 'starwar', 'skywalker',
    'ewok', 'wookie', 'wookiee', 'chewbacca', 'pod racing', 'kylo ren'
    'jedi', 'force awakens', 'empire strikes back', 'darth', 'yoda',
    'general grievous', 'sheev', 'palpatine', 'vader', 'mandalorian',
    'at st', 'george lucas', 'obi wan', 'anakin', 'han solo', 'ben solo',
    )

class StarWarsPunisher(commands.Cog):
    def __init__(self, guild_id, banlist=None, lastcall=None):
        self.guild = self.bot.get_guild(guild_id)
        self.banlist = banlist or deque([])
        self.lastcall = lastcall
        self.order66 = None
        self.role = dc.utils.find(
            lambda r: 'star wars' in r.name.lower(),
            self.guild.roles
            )
        self.manage_bans.start()

    def dump(self):
        return {
            'guild': self.guild.id,
            'banlist': self.banlist,
            'lastcall': self.lastcall,
            }

    def monitor(self, ctx):
        self.order66 = (ctx.channel.id, ctx.message.created_at+timedelta(minutes=5))

    def detect(self, msg):
        return (self.order66
            and msg.channel.id == self.order66[0]
            and any(map(msg.content.lower().__contains__, triggers))
            )

    async def punish(self, msg):
        await msg.author.add_roles(self.role, reason='Star Wars.')
        self.banlist.append((msg.author.id, msg.created_at+timedelta(minutes=30)))
        if self.lastcall is None:
            dt = None
        else:
            dt = msg.created_at - self.lastcall
        self.lastcall = msg.created_at
        return dt

    @tasks.loop(seconds=5.0)
    async def manage_bans(self):
        if self.order66 is not None and self.order66[1] < datetime.utcnow():
            await self.bot.get_channel(self.order66[0]).send('D--> The senate recedes.')
            self.order66 = None
        if self.banlist and self.banlist[0][1] < datetime.utcnow():
            await self.guild.get_member(self.banlist.popleft()[0]).remove_roles(
                self.role, reason='Star Wars timeout.'
                )


class RoleSaver(object):
    def __init__(self, fname):
        self.fname = fname
        self.load()

    def load(self):
        try:
            with open(self.fname, 'rb') as role_file:
                self.user_roles = pickle.load(role_file)
        except (OSError, EOFError):
            self.user_roles = defaultdict(dict, {})
            self.save()

    def save(self):
        with open(self.fname, 'wb') as role_file:
            pickle.dump(self.user_roles, role_file)

    def get_roles(self, member):
        return self.user_roles[member.guild.id][member.id]

    async def load_roles(self, member):
        try:
            roles = self.user_roles[member.guild.id][member.id]
        except KeyError:
            return
        await member.add_roles(
            *map(member.guild.get_role, roles),
            reason='Restore roles'
            )

    def save_roles(self, member):
        self.user_roles[member.guild.id][member.id] = [role.id for role in member.roles[1:]]
        self.save()


class MemberStalker(object):
    def __init__(self, fname):
        self.fname = fname
        self.load()

    def load(self):
        try:
            with open(self.fname, 'rb') as role_file:
                self.last_msgs = pickle.load(role_file)
        except (OSError, EOFError):
            self.last_msgs = defaultdict(dict, {})
            self.save()

    def save(self):
        with open(self.fname, 'wb') as role_file:
            pickle.dump(self.last_msgs, role_file)

    def get(self, member):
        try:
            return self.last_msgs[member.guild.id][member.id]
        except KeyError:
            return None

    def update(self, msg):
        if msg.guild is None:
            return
        self.last_msgs[msg.guild.id][msg.author.id] = msg.created_at
