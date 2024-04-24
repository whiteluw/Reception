import string
import random
import time
import threading
import discord
import pickle
import yaml
from discord.ext import commands
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


# 读取配置文件
with open("config.yaml", "r", encoding="utf-8") as file:
    config = yaml.safe_load(file)

#读取历史数据
try:
    with open("users_dic.pkl", "rb") as file:
        users_dic = pickle.load(file)
except:
    users_dic = {}

#配置文件初始化
code_dic = {}  # 字典，{discord_id : [wikidot_id,code,time]}
allowed_user_ids = config['discord']['allowed_user_ids']  # 允许执行命令的用户列表
roles_dict = {}
discord_roles = config['discord']['roles']

#Request初始化
s = requests.Session()
retries = Retry(total=10, backoff_factor=0.4, status_forcelist=[429, 500, 502, 503, 504])
s.mount("http://", HTTPAdapter(max_retries=retries))
s.mount("https://", HTTPAdapter(max_retries=retries))

#Discord初始化
intents = discord.Intents.all()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix='!', intents=intents)

# 登录
s.post(
    "https://www.wikidot.com/default--flow/login__LoginPopupScreen",
    data=dict(
        login=config["wikidot"]["username"],
        password=config["wikidot"]["password"],
        action="Login2Action",
        event="login",
    ),
)


# 清理过期验证码
def dic_clear():
    while True:
        with open("users_dic.pkl", "wb") as file:
            pickle.dump(users_dic, file)
        now = time.time()
        del_list = []
        for i in code_dic:
            if now - code_dic[i][2] >= 300:
                del_list.append(i)
        for i in del_list:
            del code_dic[i]
        time.sleep(60)

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')

# 命令处理
@bot.command(name='verify')
async def verify_command(ctx, wikidot_id=''):
    wikidot_id = ctx.message.content[8:].strip('[]').replace(' ', '-')
    print(wikidot_id)
    await ctx.reply("正在验证您的Wikidot账户，该操作完成的时间可能较长，请耐心等候...")
    discord_id = str(ctx.author.id)
    now = time.time()
    if code_dic.get(discord_id) is not None and now - code_dic[discord_id][2] < 60:
        await ctx.send('已申请验证，请在1分钟后重试')
        return
    if (intend_wikidot_id:=users_dic.get(discord_id)) is not None:
        wikidot_id = intend_wikidot_id
        await ctx.send(f'此Discord账户已绑定*{wikidot_id}*。')
    elif wikidot_id == '':
        await ctx.send('缺少wikidot用户名')
        return
    elif wikidot_id in users_dic.values():
        await ctx.send(f'wikidot账号*{wikidot_id}*已被绑定。')
        return
    userlookup = s.get(
        "https://www.wikidot.com/quickmodule.php?module=UserLookupQModule"
        f"&q={wikidot_id}"
        f"&s={config['wikidot']['siteId']}"
    ).json()
    if userlookup["users"]!=False and wikidot_id not in [user['name'] for user in userlookup["users"]]:
        await ctx.send('未找到对应Wikidot账号，请重新输入。')
        return
    to_wikidot=None
    for user in userlookup['users']:
        if user['name']==wikidot_id:
            to_wikidot=user['user_id']
            break
    memberlookup = s.get(
        "https://www.wikidot.com/quickmodule.php?module=MemberLookupQModule"
        f"&q={wikidot_id}"
        f"&s={config['wikidot']['siteId']}"
    ).json()
    isMember= memberlookup["users"]!=False and wikidot_id in [user['name'] for user in memberlookup["users"]]
    if intend_wikidot_id is not None:
        guild=ctx.guild
        author=ctx.author
        for roleid in discord_roles.values():
            if (role:=guild.get_role(roleid)) in author.roles:
                await author.remove_roles(role)
        await author.add_roles(guild.get_role(discord_roles['Member' if isMember else 'notMember']))
        await ctx.send('身份组更新完成')
        return
    code = "".join(random.sample(string.digits, 6))
    response = s.post(
            "https://www.wikidot.com/ajax-module-connector.php",
            data={
                "source":f'你的验证码是{code}，五分钟之内有效。',
                "subject":config['wikidot']['title'],
                "to_user_id":to_wikidot,
                "action":"DashboardMessageAction",
                "event":"send",
                "moduleName":"Empty",
                "callbackIndex":0,
                "wikidot_token7": s.cookies.get(
                    "wikidot_token7", domain='www.wikidot.com'
                ),
            },
        )
    print(response.text)
    code_dic[discord_id] = [wikidot_id, code, time.time(), isMember]
    await ctx.send('验证码已发送，请在五分钟内输入验证码以完成验证。')

@bot.command(name='code')
async def code_command(ctx, code: str):
    discord_id = str(ctx.author.id)
    try:
        if code_dic[discord_id][1] == code:
            role_id = discord_roles['Member'] if code_dic[discord_id][3] else discord_roles['notMember']
            guild = ctx.guild
            role = guild.get_role(role_id)
            if (guest_id:=discord_roles['Guest']) in ctx.author.roles:
                await ctx.author.remove_roles(guild.get_role(guest_id))
            if role not in ctx.author.roles:
                await ctx.author.add_roles(role)
                await ctx.reply('验证成功，身份组分配完成')
            else:
                await ctx.reply('验证成功')
            discord_name = ctx.author.nick
            print(discord_name)
            users_dic[discord_id] = code_dic[discord_id][0]
            # if users_dic[discord_id] not in discord_name:
            # await ctx.author.edit(nick=f'{discord_name}/{code_dic[discord_id][0]}')
            del code_dic[discord_id]
        else:
            await ctx.reply('验证码错误')
    except KeyError:
        await ctx.reply('没有申请验证码或验证码已过期')

@bot.command(name='check')
async def check_command(ctx, discord_id=''):
    if discord_id == '':
        discord_id = str(ctx.author.id)
    else:
        discord_id = discord_id.strip('[]<>@')
    try:
        await ctx.reply(f'该账号已绑定wikidot账号*{users_dic[discord_id]}*。')
    except KeyError:
        await ctx.reply('该账户未绑定，请稍后再试')

@bot.command(name='roleedit')
async def role_edit(ctx, action, user_id, role_id):
    if ctx.message.author.id not in allowed_user_ids:
        await ctx.send("在权限检查时出现错误：权限不足")
        return

    user = bot.get_user(int(user_id))
    member = ctx.guild.get_member(int(user_id))

    role = discord.utils.get(ctx.guild.roles, id=int(role_id))

    if user is None or member is None or role is None:
        await ctx.send("在执行命令时出现错误：无效的用户ID、成员或身份组ID")
        return

    if action == 'add':
        await member.add_roles(role)
        roles_dict.setdefault(str(user.id), []).append(str(role.id))
        await ctx.send(f"已添加*{user.name}*到*{role.name}*身份组")
    elif action == 'del':
        if str(role.id) in roles_dict.get(str(user.id), []):
            await member.remove_roles(role)
            roles_dict[str(user.id)].remove(str(role.id))
            await ctx.send(f"已从*{user.name}*移除*{role.name}*身份组")
        else:
            await ctx.send(f"错误：*{user.name}*不在*{role.name}*身份组中")

# 启动清理线程
threading.Thread(target=dic_clear, args=()).start()

# 运行bot
if __name__ == '__main__':
    bot.run(config['discord']['token'])
