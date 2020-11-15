# Moderation data classes
import re
import os
import pickle
from datetime import datetime, timedelta
from collections import defaultdict, deque
from random import randrange
from itertools import islice

import discord as dc
from discord.ext import tasks, commands

from cogs_textbanks import query_bank, response_bank

guild_whitelist = (152981670507577344, 663452978237407262, 402880303065989121, 431698070510501891)

def callback(): # Lambdas can't be pickled, but named functions can.
    return {
    'usrlog': None, 'msglog': None, 'modlog': None,
    'autoreact': set(), 'star_wars': {}, 'ignoreplebs': set(), 'enablelatex': set(),
    }

class Singleton(object):
    _self_instance_ref = None
    def __new__(cls, *args, **kwargs):
        if cls._self_instance_ref is None:
            cls._self_instance_ref = super().__new__(cls)
        return cls._self_instance_ref


class GuildConfig(Singleton):
    def __init__(self, bot, fname):
        StarWarsPunisher.bot = bot
        self.bot = bot
        self.fname = os.path.join('data', fname)
        self.punishers = {}
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etrace):
        self.save()

    def save(self):
        for guild_id, config in self.mod_channels.items():
            try:
                config['star_wars'] = self.punishers[guild_id].dump()
            except KeyError:
                if 'star_wars' not in config:
                    config['star_wars'] = None
        with open(self.fname, 'wb') as config_file:
            pickle.dump(self.mod_channels, config_file)

    def load(self):
        try:
            with open(self.fname, 'rb') as config_file:
                self.mod_channels = pickle.load(config_file)
        except (OSError, EOFError):
            self.mod_channels = defaultdict(callback)
            self.save()
        else:
            for guild, config in self.mod_channels.copy().items():
                if guild not in guild_whitelist:
                    del self.mod_channels[guild]
                    continue

    async def log(self, guild, log, *args, **kwargs):
        await self.bot.get_channel(
            self.mod_channels[guild.id][log]
            ).send(*args, **kwargs)

    def getlog(self, guild, log):
        return self.mod_channels[guild.id][log]

    def getcmd(self, ctx):
        perms = ctx.author.guild_permissions
        return (
            perms.administrator or perms.view_audit_log or perms.manage_guild or perms.manage_roles
            or ctx.channel.id not in self.mod_channels[ctx.guild.id]['ignoreplebs']
            )
    def getltx(self, ctx):
        perms = ctx.author.guild_permissions
        return (
            perms.administrator or perms.view_audit_log or perms.manage_guild or perms.manage_roles
            or ctx.channel.id in self.mod_channels[ctx.guild.id]['enablelatex']
            )

    def setlog(self, ctx, log):
        if log not in {'usrlog', 'msglog', 'modlog'}:
            raise ValueError(response_bank.config_args_error.format(log=log))
        self.mod_channels[ctx.guild.id][log] = ctx.channel.id
        self.save()

    def toggle(self, ctx, field):
        config = self.mod_channels[ctx.guild.id][field]
        channel_id = ctx.channel.id
        if channel_id in config:
            config.remove(channel_id)
            return False
        else:
            config.add(channel_id)
            return True

    def set_containment(self, ctx):
        guild_id = ctx.guild.id
        star_wars = self.mod_channels[guild_id]['star_wars']
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
        dt = await self.punishers[msg.guild.id].punish(msg)
        self.save()
        return dt
        
    def log_linky(self, msg):
        with open('spat.txt', 'a', encoding='utf-8') as lfile:
            lfile.write(msg.content.strip() + '\n')
    
    def random_linky(self, msg):
        try:
            with open('spat.txt', 'r', encoding='utf-8') as lfile:
                lcount = sum(1 for _ in lfile)
                lfile.seek(0)
                return next(islice(lfile, randrange(lcount), None))
        except FileNotFoundError:
            with open('spat.txt', 'w', encoding='utf-8') as lfile:
                lfile.write('i love dirt so much\n')
            return 'i love dirt so much\n'


triggers = [*map(re.compile, (
    r'\bstar\s*wars?\b', r'\bskywalker\b', r'\banakin\b', r'\bjedi\b',
    r'\bpod racing\b', r'\byoda\b', r'\bdarth\b', r'\bvader\b',
    r'\bewoks?\b', r'\bwookiee?s?\b', r'\bchewbacca\b', r'\bdeath star\b',
    r'\bmandalorian\b', r'\bobi wan( kenobi)?\b', r'\b(ha|be)n solo\b', r'\bkylo ren\b',
    r'\bforce awakens?\b', r'\bempire strikes? back\b', r'\bat[- ]st\b', r'\bgeorge lucas\b',
    r'\bgeneral grievous\b', r'\bsheev( palpatine)?\b', r'\b(emperor )?palpatine\b',
    ))]

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

    def dump(self):
        return {
            'guild': self.guild.id,
            'banlist': self.banlist,
            'lastcall': self.lastcall,
            }

    def monitor(self, ctx):
        if self.order66 is None:
            self.manage_bans.start()
        self.order66 = (ctx.channel.id, ctx.message.created_at+timedelta(minutes=5))

    def detect(self, msg):
        content = msg.content.lower()
        return bool(self.order66
            and msg.channel.id == self.order66[0]
            and (msg.author.id == 207991389613457408
                or any(pattern.search(content) for pattern in triggers)
                ))

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
        if self.banlist and self.banlist[0][1] < datetime.utcnow():
            await self.guild.get_member(self.banlist.popleft()[0]).remove_roles(
                self.role, reason='Star Wars timeout.'
                )
        if self.order66 is not None:
            if self.order66[1] < datetime.utcnow():
                await self.bot.get_channel(self.order66[0]).send(
                    response_bank.star_wars_punish_completion
                    )
                self.order66 = None
        elif not self.banlist:
            self.manage_bans.cancel()


def guild_callback():
    return {'first_join': None, 'last_seen': None, 'last_roles': []}

def member_callback():
    return defaultdict(guild_callback, {'avatar_count': 0, 'latex_count': 0})

class MemberStalker(Singleton):
    def __init__(self, fname):
        self.fname = os.path.join('data', fname)
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etrace):
        self.save()

    def save(self):
        with open(self.fname, 'wb') as member_file:
            pickle.dump(self.member_data, member_file)

    def load(self):
        try:
            with open(self.fname, 'rb') as member_file:
                self.member_data = pickle.load(member_file)
        except (OSError, EOFError):
            self.member_data = defaultdict(member_callback)
            self.save()

    def get(self, field, member):
        return self.member_data[member.id][member.guild.id][field]

    def update(self, field, data):
        if field == 'first_join': # data is a discord.Member instance
            member_data = self.member_data[data.id][data.guild.id]
            if not member_data[field]:
                member_data[field] = data.joined_at
        elif field == 'last_seen': # data is a discord.Message instance
            self.member_data[data.author.id][data.guild.id][field] = data.created_at
        elif field == 'last_roles': # data is a discord.Member instance
            self.member_data[data.id][data.guild.id][field] = [role.id for role in data.roles[1:]]

    async def load_roles(self, member):
        await member.add_roles(
            *map(member.guild.get_role, self.member_data[member.id][member.guild.id]['last_roles']),
            reason='Restore last roles'
            )


def dictgrabber():
    return defaultdict(dict)

class EmojiRoles(Singleton):
    def __init__(self, fname):
        self.fname = os.path.join('data', fname)
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etrace):
        self.save()

    def __iter__(self):
        for key, value in self.role_data.items():
            yield (key, value)

    def save(self):
        # Purge all empty message entries for sanity's sake.
        for chn_id, msg_dict in self.role_data.items():
            for msg_id in list(msg_dict):
                if not msg_dict[msg_id]:
                    del msg_dict[msg_id]
        with open(self.fname, 'wb') as rolefile:
            pickle.dump(self.role_data, rolefile)

    def load(self):
        try:
            with open(self.fname, 'rb') as rolefile:
                self.role_data = pickle.load(rolefile)
        except (OSError, EOFError):
            self.role_data = defaultdict(dictgrabber)
            self.save()

    @staticmethod
    def get_react_id(react):
        if isinstance(react, dc.Reaction):
            react = react.emoji
        if isinstance(react, (dc.Emoji, dc.PartialEmoji)):
            return react.id
        return hash(react)

    def get_reactmap(self, chn_id, msg_id):
        return self.role_data[chn_id][msg_id]
            
    def add_reaction(self, msg, react, role):
        self.role_data[msg.channel.id][msg.id][self.get_react_id(react)] = role.id
        self.save()

    def remove_message(self, msg):
        try:
            del self.role_data[msg.channel.id][msg.id]
        except KeyError:
            return
        self.save()
    
    def remove_reaction(self, msg, react):
        try:
            del self.role_data[msg.channel.id][msg.id][self.get_react_id(react)]
        except KeyError:
            print(response_bank.role_remove_react_error.format(react=react, msg=msg))
            return
        self.save()


def category_callback():
    return defaultdict(set)

class RoleCategories(Singleton):
    def __init__(self, fname):
        self.fname = os.path.join('data', fname)
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etrace):
        self.save()

    def save(self):
        with open(self.fname, 'wb') as rolefile:
            pickle.dump(self.category_data, rolefile)

    def load(self):
        try:
            with open(self.fname, 'rb') as catfile:
                self.category_data = pickle.load(catfile)
        except (OSError, EOFError):
            self.category_data = defaultdict(category_callback)
            self.save()    
    
    def add_category(self, guild, category, roles):
        self.category_data[guild.id][category].update(roles)
        self.save()

    def remove_category(self, guild, category):
        try:
            del self.category_data[guild.id][category]
        except KeyError:
            return False
        self.save()
        return True

    async def purge_category(self, role, member):
        for category in self.category_data[role.guild.id].values():
            if role.id in category:
                break
        else:
            return False
        for member_role in member.roles:
            if member_role.id in category:
                await member.remove_roles(member_role)
        return True
            
    
class Suggestions(Singleton):
    def __init__(self, fname):
        self.fname = os.path.join('data', fname)
        self.load()

    def __enter__(self):
        return self

    def __exit__(self, etype, evalue, etrace):
        self.save()
        
    def load(self):
        try:
            with open(self.fname, 'rb') as suggests:
                self.suggestions = pickle.load(suggests)
            if isinstance(self.suggestions, defaultdict):
                self.suggestions = dict(self.suggestions)
        except (OSError, EOFError):
            self.suggestions = {}
            self.save()

    def save(self):
        with open(self.fname, 'wb') as suggests:
            pickle.dump(self.suggestions, suggests)
            
    def add_suggestion(self, msg_id, author, channel):
        self.suggestions[msg_id] = (channel, author)
        self.save()

    def get_suggestion(self, ctx, msg_id):
        chn_id, usr_id = self.suggestions[msg_id]
        channel = ctx.get_channel(chn_id)
        return (channel, channel.guild.get_member(usr_id))
        
    def remove_suggestion(self, msg_id):
        removed = self.suggestions.pop(msg_id)