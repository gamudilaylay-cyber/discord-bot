import os
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import tasks

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
TOKEN    = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0"))
LIVE_LIST_CHANNEL_ID = 1511774093949669417

# ─────────────────────────────────────────────
#  IN-MEMORY STORES
# ─────────────────────────────────────────────
warnings_store: dict[str, list[dict]] = {}
warn_counter: list[int] = [0]
muendliche_counts: dict[str, int] = {}
live_message_id: Optional[int] = None

# ─────────────────────────────────────────────
#  ROLE NAME CONSTANTS
# ─────────────────────────────────────────────
WARN_ROLES       = ["Verwarnung 1/3", "Verwarnung 2/3", "Verwarnung 3/3"]
MUENDLICHE_ROLES = ["Mündliche Verwarnung 1", "Mündliche Verwarnung 2"]
MITARBEITER_ROLE = "👤【Mitarbeiter*in】"
SVG_BASE         = "「📄 SVG｜schaden versichert」"
LVV_BASE         = "「📄 LVV｜leben versichert」"
INSURANCE_COLOR  = 0x1f8b4c

DURATION_ORDER = (
    ["1 Tag"]
    + [f"{i} Tage" for i in range(2, 31)]
    + ["1 Monat"]
)

# ─────────────────────────────────────────────
#  COLORS
# ─────────────────────────────────────────────
C_RED    = 0xe74c3c
C_GREEN  = 0x2ecc71
C_YELLOW = 0xf1c40f
C_ORANGE = 0xe67e22
C_BLUE   = 0x3498db
C_PURPLE = 0x9b59b6
C_DARK   = 0x2c2f33
C_CYAN   = 0x1abc9c
C_GOLD   = 0xffd700

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────
def _next_warn_id() -> str:
    warn_counter[0] += 1
    return f"W{warn_counter[0]:04d}"

def add_warning(user_id: str, mod_id: str, reason: str) -> dict:
    w = {"id": _next_warn_id(), "user_id": user_id, "mod_id": mod_id,
         "reason": reason, "timestamp": datetime.now(timezone.utc)}
    warnings_store.setdefault(user_id, []).append(w)
    return w

def get_warnings(user_id: str) -> list[dict]:
    return warnings_store.get(user_id, [])

def remove_warning(user_id: str, warn_id: str) -> bool:
    ws = warnings_store.get(user_id, [])
    for i, w in enumerate(ws):
        if w["id"] == warn_id.upper():
            ws.pop(i)
            return True
    return False

def get_muendliche(user_id: str) -> int:
    return muendliche_counts.get(user_id, 0)

def add_muendliche(user_id: str) -> int:
    new = min(muendliche_counts.get(user_id, 0) + 1, 2)
    muendliche_counts[user_id] = new
    return new

def make_embed(
    color: int,
    title: str,
    description: Optional[str] = None,
    fields: Optional[list[dict]] = None,
    footer: Optional[str] = None,
    thumbnail: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, color=color,
                          timestamp=datetime.now(timezone.utc))
    if description:
        embed.description = description
    for f in (fields or []):
        embed.add_field(name=f["name"], value=f["value"],
                        inline=f.get("inline", False))
    if footer:
        embed.set_footer(text=footer)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    return embed

def find_role(guild: discord.Guild, name: str) -> Optional[discord.Role]:
    return discord.utils.get(guild.roles, name=name)

# ─────────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot   = discord.Client(intents=intents)
tree  = app_commands.CommandTree(bot)
GUILD = discord.Object(id=GUILD_ID)

# ─────────────────────────────────────────────
#  /verwarnung
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="verwarnung",
              description="Verwarnt ein Mitglied offiziell (Stufe 1/3 bis 3/3)")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund der Verwarnung")
async def cmd_verwarnung(interaction: discord.Interaction,
                         mitglied: discord.Member, grund: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    w       = add_warning(str(mitglied.id), str(interaction.user.id), grund)
    count   = len(get_warnings(str(mitglied.id)))
    stage   = min(count, 3)

    # Assign correct warning role, remove others
    new_role_name = WARN_ROLES[stage - 1] if stage <= 3 else None
    new_role = find_role(interaction.guild, new_role_name) if new_role_name else None
    if not new_role and new_role_name:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Rolle nicht gefunden",
            f"Erstelle bitte die Rolle `{new_role_name}` auf dem Server."),
            ephemeral=True)

    for rn in WARN_ROLES:
        r = find_role(interaction.guild, rn)
        if r and r in mitglied.roles and rn != new_role_name:
            await mitglied.remove_roles(r)
    if new_role:
        await mitglied.add_roles(new_role)

    clr  = C_YELLOW if stage == 1 else C_ORANGE if stage == 2 else C_RED
    emoji = "🟡" if stage == 1 else "🟠" if stage == 2 else "🔴"
    await interaction.response.send_message(embed=make_embed(
        clr, f"{emoji} Offizielle Verwarnung ausgesprochen",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",          "value": mitglied.mention,           "inline": True},
            {"name": "🔖 Warn-ID",            "value": f"`{w['id']}`",             "inline": True},
            {"name": "📊 Stufe",              "value": f"**{stage}/3**",           "inline": True},
            {"name": "🏷️ Rolle",             "value": f"`{new_role_name}`" if new_role_name else "—", "inline": True},
            {"name": "📝 Grund",              "value": f"> {grund}"},
            {"name": "👮 Moderator",          "value": interaction.user.mention,   "inline": True},
        ],
        footer="⚠️ Bei erneutem Verstoß folgt die nächste Stufe" if stage < 3
               else "🚨 3/3 Verwarnungen — weitere Maßnahmen empfohlen"))

    try:
        await mitglied.send(embed=make_embed(
            clr, f"{emoji} Du hast eine offizielle Verwarnung erhalten",
            description=f"Du wurdest auf **{interaction.guild.name}** verwarnt.",
            fields=[
                {"name": "📊 Stufe",  "value": f"**{stage}/3**"},
                {"name": "📝 Grund",  "value": f"> {grund}"},
                {"name": "👮 Moderator", "value": str(interaction.user)},
            ], footer="Bitte halte dich an die Serverregeln"))
    except discord.Forbidden:
        pass

# ─────────────────────────────────────────────
#  /mündliche
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="mündliche",
              description="Mündliche Verwarnung (Stufe 1 oder 2)")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund")
async def cmd_muendliche(interaction: discord.Interaction,
                         mitglied: discord.Member, grund: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    prev = get_muendliche(str(mitglied.id))
    if prev >= 2:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "⛔ Maximum erreicht",
            f"{mitglied.mention} hat bereits **Mündliche Verwarnung 2**. "
            "Nutze `/verwarnung` für eine offizielle Verwarnung.",
            thumbnail=str(mitglied.display_avatar)), ephemeral=True)

    level = add_muendliche(str(mitglied.id))
    role1 = find_role(interaction.guild, MUENDLICHE_ROLES[0])
    role2 = find_role(interaction.guild, MUENDLICHE_ROLES[1])

    if level == 1:
        if not role1:
            return await interaction.response.send_message(embed=make_embed(
                C_RED, "❌ Rolle nicht gefunden",
                f"Erstelle die Rolle `{MUENDLICHE_ROLES[0]}` auf dem Server."), ephemeral=True)
        await mitglied.add_roles(role1)
    else:
        if not role2:
            return await interaction.response.send_message(embed=make_embed(
                C_RED, "❌ Rolle nicht gefunden",
                f"Erstelle die Rolle `{MUENDLICHE_ROLES[1]}` auf dem Server."), ephemeral=True)
        if role1 and role1 in mitglied.roles:
            await mitglied.remove_roles(role1)
        await mitglied.add_roles(role2)

    clr   = C_YELLOW if level == 1 else C_ORANGE
    emoji = "🟡" if level == 1 else "🔴"
    await interaction.response.send_message(embed=make_embed(
        clr, f"{emoji} Mündliche Verwarnung {level} ausgesprochen",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",  "value": mitglied.mention,         "inline": True},
            {"name": "📊 Stufe",     "value": f"**{level}/2**",          "inline": True},
            {"name": "🏷️ Rolle",    "value": f"`{MUENDLICHE_ROLES[level-1]}`", "inline": True},
            {"name": "📝 Grund",     "value": f"> {grund}"},
            {"name": "👮 Moderator", "value": interaction.user.mention,  "inline": True},
        ],
        footer="⚠️ Bei erneutem Verstoß folgt Mündliche Verwarnung 2" if level == 1
               else "🚨 Maximum — bei weiteren Verstößen offizielle Verwarnung"))

    try:
        await mitglied.send(embed=make_embed(
            clr, f"{emoji} Du hast eine Mündliche Verwarnung {level} erhalten",
            description=f"Du wurdest auf **{interaction.guild.name}** mündlich verwarnt.",
            fields=[
                {"name": "📊 Stufe",     "value": f"**{level}/2**"},
                {"name": "📝 Grund",     "value": f"> {grund}"},
                {"name": "👮 Moderator", "value": str(interaction.user)},
            ], footer="Bitte halte dich zukünftig an die Serverregeln"))
    except discord.Forbidden:
        pass

# ─────────────────────────────────────────────
#  /verwarnungen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="verwarnungen",
              description="Zeigt alle Verwarnungen eines Mitglieds")
@app_commands.describe(mitglied="Das Mitglied")
async def cmd_verwarnungen(interaction: discord.Interaction, mitglied: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    ws = get_warnings(str(mitglied.id))
    if not ws:
        return await interaction.response.send_message(embed=make_embed(
            C_GREEN, "✅ Keine Verwarnungen",
            f"{mitglied.mention} hat keine aktiven Verwarnungen.",
            thumbnail=str(mitglied.display_avatar)))

    lines = "\n\n".join(
        f"**{i+1}.** `{w['id']}` — {w['reason']}\n"
        f"↳ <t:{int(w['timestamp'].timestamp())}:R>"
        for i, w in enumerate(ws)
    )
    await interaction.response.send_message(embed=make_embed(
        C_YELLOW, f"⚠️ Verwarnungen — {mitglied.display_name}",
        description=lines[:4000],
        thumbnail=str(mitglied.display_avatar),
        fields=[{"name": "📋 Gesamt", "value": f"**{len(ws)}**", "inline": True}],
        footer="Warn-IDs können mit /verwarnung_entfernen gelöscht werden"))

# ─────────────────────────────────────────────
#  /verwarnung_entfernen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="verwarnung_entfernen",
              description="Entfernt eine spezifische Verwarnung per ID")
@app_commands.describe(mitglied="Das Mitglied", warn_id="Warn-ID (z.B. W0001)", grund="Grund")
async def cmd_verwarnung_entfernen(interaction: discord.Interaction,
                                   mitglied: discord.Member,
                                   warn_id: str, grund: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    if not remove_warning(str(mitglied.id), warn_id):
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Nicht gefunden",
            f"Keine Verwarnung mit ID `{warn_id.upper()}` für {mitglied.mention} gefunden."),
            ephemeral=True)

    await interaction.response.send_message(embed=make_embed(
        C_GREEN, "✅ Verwarnung entfernt",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",   "value": mitglied.mention,              "inline": True},
            {"name": "🔖 Warn-ID",    "value": f"`{warn_id.upper()}`",         "inline": True},
            {"name": "📝 Grund",      "value": f"> {grund}"},
            {"name": "👮 Entfernt von","value": interaction.user.mention,      "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /kündigung
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="kündigung",
              description="Kündigt einem Mitglied — entfernt die Mitarbeiter-Rolle")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund der Kündigung")
async def cmd_kuendigung(interaction: discord.Interaction,
                         mitglied: discord.Member, grund: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    role = find_role(interaction.guild, MITARBEITER_ROLE)
    if not role:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Rolle nicht gefunden",
            f"Die Rolle `{MITARBEITER_ROLE}` wurde nicht gefunden."), ephemeral=True)
    if role not in mitglied.roles:
        return await interaction.response.send_message(embed=make_embed(
            C_YELLOW, "⚠️ Rolle nicht vergeben",
            f"{mitglied.mention} hat die Rolle {role.mention} nicht."), ephemeral=True)

    await mitglied.remove_roles(role)
    await interaction.response.send_message(embed=make_embed(
        C_RED, "📋 Kündigung ausgesprochen",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",        "value": mitglied.mention,         "inline": True},
            {"name": "🏷️ Entfernte Rolle", "value": role.mention,             "inline": True},
            {"name": "📝 Grund",           "value": f"> {grund}"},
            {"name": "👮 Ausgestellt von", "value": interaction.user.mention,  "inline": True},
        ], footer="Mitarbeiterstatus wurde entzogen"))

    try:
        await mitglied.send(embed=make_embed(
            C_RED, "📋 Deine Kündigung",
            description=f"Dein Mitarbeiterstatus auf **{interaction.guild.name}** wurde beendet.",
            fields=[
                {"name": "📝 Grund",      "value": f"> {grund}"},
                {"name": "👮 Ausgestellt","value": str(interaction.user)},
            ], footer="Bei Fragen wende dich an die Serverleitung"))
    except discord.Forbidden:
        pass

# ─────────────────────────────────────────────
#  /beförderung
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="beförderung",
              description="Befördert ein Mitglied — fügt eine Rolle hinzu (alte bleibt)")
@app_commands.describe(mitglied="Das Mitglied", rolle="Die neue Rolle", grund="Grund")
async def cmd_befoerderung(interaction: discord.Interaction,
                           mitglied: discord.Member,
                           rolle: discord.Role, grund: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)
    if rolle in mitglied.roles:
        return await interaction.response.send_message(embed=make_embed(
            C_YELLOW, "⚠️ Bereits vergeben",
            f"{mitglied.mention} hat diese Rolle bereits."), ephemeral=True)

    await mitglied.add_roles(rolle)
    await interaction.response.send_message(embed=make_embed(
        C_GREEN, "🎉 Beförderung",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",  "value": mitglied.mention,        "inline": True},
            {"name": "🏆 Neue Rolle","value": rolle.mention,            "inline": True},
            {"name": "📝 Grund",     "value": f"> {grund}"},
            {"name": "👮 Befördert von","value": interaction.user.mention,"inline": True},
        ], footer="Herzlichen Glückwunsch zur Beförderung!"))

    try:
        await mitglied.send(embed=make_embed(
            C_GREEN, "🎉 Du wurdest befördert!",
            description=f"Glückwunsch! Du hast auf **{interaction.guild.name}** eine neue Rolle erhalten.",
            fields=[
                {"name": "🏆 Neue Rolle",  "value": rolle.name},
                {"name": "📝 Grund",       "value": f"> {grund}"},
                {"name": "👮 Befördert von","value": str(interaction.user)},
            ], footer="Weiter so — du machst einen tollen Job!"))
    except discord.Forbidden:
        pass

# ─────────────────────────────────────────────
#  /degradierung
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="degradierung",
              description="Degradiert ein Mitglied — fügt niedrigere Rolle hinzu (alte bleibt)")
@app_commands.describe(mitglied="Das Mitglied", rolle="Die neue (niedrigere) Rolle", grund="Grund")
async def cmd_degradierung(interaction: discord.Interaction,
                           mitglied: discord.Member,
                           rolle: discord.Role, grund: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await mitglied.add_roles(rolle)
    await interaction.response.send_message(embed=make_embed(
        C_ORANGE, "📉 Degradierung",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",     "value": mitglied.mention,        "inline": True},
            {"name": "🔽 Neue Rolle",   "value": rolle.mention,            "inline": True},
            {"name": "📝 Grund",        "value": f"> {grund}"},
            {"name": "👮 Degradiert von","value": interaction.user.mention,"inline": True},
        ], footer="Bestehende Rollen wurden beibehalten"))

    try:
        await mitglied.send(embed=make_embed(
            C_ORANGE, "📉 Degradierung",
            description=f"Dein Rang auf **{interaction.guild.name}** wurde angepasst.",
            fields=[
                {"name": "🔽 Neue Rolle",   "value": rolle.name},
                {"name": "📝 Grund",        "value": f"> {grund}"},
                {"name": "👮 Degradiert von","value": str(interaction.user)},
            ], footer="Bei Fragen wende dich an die Serverleitung"))
    except discord.Forbidden:
        pass

# ─────────────────────────────────────────────
#  /kick
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="kick", description="Kickt ein Mitglied vom Server")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund des Kicks")
async def cmd_kick(interaction: discord.Interaction,
                   mitglied: discord.Member, grund: str):
    if not interaction.user.guild_permissions.kick_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)
    if not mitglied.guild_permissions < interaction.user.guild_permissions:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Nicht möglich",
            "Dieses Mitglied kann nicht gekickt werden."), ephemeral=True)

    try:
        await mitglied.send(embed=make_embed(
            C_RED, "👢 Du wurdest gekickt",
            description=f"Du wurdest von **{interaction.guild.name}** gekickt.",
            fields=[{"name": "📝 Grund", "value": f"> {grund}"}]))
    except discord.Forbidden:
        pass

    await mitglied.kick(reason=grund)
    await interaction.response.send_message(embed=make_embed(
        C_RED, "👢 Mitglied gekickt",
        fields=[
            {"name": "👤 Mitglied",    "value": str(mitglied),             "inline": True},
            {"name": "📝 Grund",       "value": f"> {grund}"},
            {"name": "👮 Gekickt von", "value": interaction.user.mention,   "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /ban
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="ban", description="Bannt ein Mitglied vom Server")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund des Bans",
                        nachrichten_tage="Nachrichten der letzten X Tage löschen (0-7)")
async def cmd_ban(interaction: discord.Interaction, mitglied: discord.Member,
                  grund: str, nachrichten_tage: Optional[int] = 0):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)
    if not mitglied.guild_permissions < interaction.user.guild_permissions:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Nicht möglich",
            "Dieses Mitglied kann nicht gebannt werden."), ephemeral=True)

    days = max(0, min(7, nachrichten_tage or 0))

    try:
        await mitglied.send(embed=make_embed(
            C_DARK, "🔨 Du wurdest gebannt",
            description=f"Du wurdest von **{interaction.guild.name}** permanent gebannt.",
            fields=[{"name": "📝 Grund", "value": f"> {grund}"}],
            footer="Kontaktiere die Serverleitung bei Einwänden"))
    except discord.Forbidden:
        pass

    await mitglied.ban(reason=grund, delete_message_days=days)
    await interaction.response.send_message(embed=make_embed(
        C_DARK, "🔨 Mitglied gebannt",
        fields=[
            {"name": "👤 Mitglied",            "value": str(mitglied),            "inline": True},
            {"name": "📝 Grund",               "value": f"> {grund}"},
            {"name": "👮 Gebannt von",         "value": interaction.user.mention,  "inline": True},
            {"name": "🗑️ Nachrichten gelöscht","value": f"{days} Tag(e)",          "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /unban
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="unban", description="Entbannt ein Mitglied per User-ID")
@app_commands.describe(user_id="Die User-ID des gebannten Mitglieds", grund="Grund des Entbannens")
async def cmd_unban(interaction: discord.Interaction, user_id: str, grund: str):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    try:
        uid  = int(user_id)
        user = await bot.fetch_user(uid)
        await interaction.guild.unban(user, reason=grund)
        await interaction.response.send_message(embed=make_embed(
            C_GREEN, "✅ Mitglied entbannt",
            thumbnail=str(user.display_avatar),
            fields=[
                {"name": "👤 Mitglied",     "value": f"{user} (`{uid}`)",       "inline": True},
                {"name": "📝 Grund",        "value": f"> {grund}"},
                {"name": "👮 Entbannt von", "value": interaction.user.mention,   "inline": True},
            ]))
    except Exception:
        await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Fehler",
            "Benutzer nicht gefunden oder nicht gebannt."), ephemeral=True)

# ─────────────────────────────────────────────
#  /timeout
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="timeout", description="Gibt einem Mitglied einen Timeout")
@app_commands.describe(mitglied="Das Mitglied", minuten="Dauer in Minuten (1-40320)", grund="Grund")
async def cmd_timeout(interaction: discord.Interaction,
                      mitglied: discord.Member, minuten: int, grund: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    minuten = max(1, min(40320, minuten))
    until   = discord.utils.utcnow() + timedelta(minutes=minuten)

    await mitglied.timeout(until, reason=grund)
    await interaction.response.send_message(embed=make_embed(
        C_PURPLE, "🔇 Timeout vergeben",
        thumbnail=str(mitglied.display_avatar),
        fields=[
            {"name": "👤 Mitglied",  "value": mitglied.mention,                                    "inline": True},
            {"name": "⏱️ Dauer",    "value": f"**{minuten} Minute(n)**",                           "inline": True},
            {"name": "🔓 Endet",    "value": f"<t:{int(until.timestamp())}:R>",                    "inline": True},
            {"name": "📝 Grund",    "value": f"> {grund}"},
            {"name": "👮 Moderator","value": interaction.user.mention,                              "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /userinfo
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="userinfo", description="Zeigt Informationen über ein Mitglied")
@app_commands.describe(mitglied="Das Mitglied (leer = du selbst)")
async def cmd_userinfo(interaction: discord.Interaction,
                       mitglied: Optional[discord.Member] = None):
    m  = mitglied or interaction.user
    ws = get_warnings(str(m.id))

    top_roles = sorted(
        [r for r in m.roles if r.id != interaction.guild.id],
        key=lambda r: r.position, reverse=True
    )
    roles_str = " ".join(r.mention for r in top_roles[:8]) or "Keine"

    await interaction.response.send_message(embed=make_embed(
        m.color.value if m.color.value else C_BLUE,
        f"👤 {m.display_name}",
        thumbnail=str(m.display_avatar.url),
        fields=[
            {"name": "🆔 ID",                 "value": f"`{m.id}`",                                    "inline": True},
            {"name": "🏷️ Tag",               "value": str(m),                                         "inline": True},
            {"name": "🤖 Bot",               "value": "Ja" if m.bot else "Nein",                       "inline": True},
            {"name": "📅 Discord beigetreten","value": f"<t:{int(m.created_at.timestamp())}:D>",       "inline": True},
            {"name": "📥 Server beigetreten", "value": f"<t:{int(m.joined_at.timestamp())}:D>" if m.joined_at else "—", "inline": True},
            {"name": "⚠️ Verwarnungen",       "value": f"**{len(ws)}**",                               "inline": True},
            {"name": f"🎭 Rollen ({len(top_roles)})", "value": roles_str},
        ]))

# ─────────────────────────────────────────────
#  /serverinfo
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="serverinfo", description="Zeigt Informationen über den Server")
async def cmd_serverinfo(interaction: discord.Interaction):
    g      = interaction.guild
    owner  = await g.fetch_member(g.owner_id)
    text_c = sum(1 for c in g.channels if isinstance(c, discord.TextChannel))
    voice_c= sum(1 for c in g.channels if isinstance(c, discord.VoiceChannel))

    await interaction.response.send_message(embed=make_embed(
        C_CYAN, f"🏰 {g.name}",
        thumbnail=str(g.icon.url) if g.icon else None,
        fields=[
            {"name": "🆔 Server-ID",       "value": f"`{g.id}`",                              "inline": True},
            {"name": "👑 Eigentümer",       "value": str(owner),                               "inline": True},
            {"name": "📅 Erstellt am",     "value": f"<t:{int(g.created_at.timestamp())}:D>", "inline": True},
            {"name": "👥 Mitglieder",      "value": f"**{g.member_count}**",                  "inline": True},
            {"name": "💬 Textkanäle",      "value": f"**{text_c}**",                           "inline": True},
            {"name": "🔊 Sprachkanäle",    "value": f"**{voice_c}**",                          "inline": True},
            {"name": "🎭 Rollen",          "value": f"**{len(g.roles)}**",                     "inline": True},
            {"name": "😀 Emojis",          "value": f"**{len(g.emojis)}**",                    "inline": True},
            {"name": "✅ Verifizierung",   "value": str(g.verification_level),                 "inline": True},
        ],
        footer=f"Boost-Level: {g.premium_tier} • {g.premium_subscription_count or 0} Boosts"))

# ─────────────────────────────────────────────
#  /rolle_geben
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="rolle_geben", description="Gibt einem Mitglied eine Rolle")
@app_commands.describe(mitglied="Das Mitglied", rolle="Die Rolle", grund="Grund")
async def cmd_rolle_geben(interaction: discord.Interaction,
                          mitglied: discord.Member, rolle: discord.Role, grund: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await mitglied.add_roles(rolle)
    await interaction.response.send_message(embed=make_embed(
        C_CYAN, "🏷️ Rolle vergeben",
        fields=[
            {"name": "👤 Mitglied", "value": mitglied.mention,       "inline": True},
            {"name": "🏷️ Rolle",   "value": rolle.mention,           "inline": True},
            {"name": "📝 Grund",   "value": f"> {grund}"},
            {"name": "👮 Von",     "value": interaction.user.mention, "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /rolle_entfernen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="rolle_entfernen",
              description="Entfernt eine Rolle von einem Mitglied")
@app_commands.describe(mitglied="Das Mitglied", rolle="Die Rolle", grund="Grund")
async def cmd_rolle_entfernen(interaction: discord.Interaction,
                              mitglied: discord.Member, rolle: discord.Role, grund: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await mitglied.remove_roles(rolle)
    await interaction.response.send_message(embed=make_embed(
        C_ORANGE, "🏷️ Rolle entfernt",
        fields=[
            {"name": "👤 Mitglied", "value": mitglied.mention,       "inline": True},
            {"name": "🏷️ Rolle",   "value": rolle.mention,           "inline": True},
            {"name": "📝 Grund",   "value": f"> {grund}"},
            {"name": "👮 Von",     "value": interaction.user.mention, "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /clear
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="clear", description="Löscht Nachrichten im Kanal (max 100)")
@app_commands.describe(anzahl="Anzahl der Nachrichten (1-100)", grund="Grund")
async def cmd_clear(interaction: discord.Interaction, anzahl: int, grund: str):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    anzahl  = max(1, min(100, anzahl))
    deleted = await interaction.channel.purge(limit=anzahl)
    await interaction.response.send_message(embed=make_embed(
        C_CYAN, "🗑️ Nachrichten gelöscht",
        fields=[
            {"name": "🗑️ Gelöscht", "value": f"**{len(deleted)}** Nachrichten", "inline": True},
            {"name": "📺 Kanal",    "value": interaction.channel.mention,        "inline": True},
            {"name": "📝 Grund",    "value": f"> {grund}"},
            {"name": "👮 Von",      "value": interaction.user.mention,            "inline": True},
        ]), ephemeral=True)

# ─────────────────────────────────────────────
#  /ankündigung
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="ankündigung",
              description="Sendet eine offizielle Ankündigung in einen Kanal")
@app_commands.describe(kanal="Zielkanal", titel="Titel", nachricht="Inhalt", grund="Interne Notiz")
async def cmd_ankuendigung(interaction: discord.Interaction,
                           kanal: discord.TextChannel,
                           titel: str, nachricht: str, grund: str):
    if not interaction.user.guild_permissions.manage_messages:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await kanal.send(embed=make_embed(
        C_GOLD, f"📢 {titel}", description=nachricht,
        footer=f"Ankündigung von {interaction.user}"))

    await interaction.response.send_message(embed=make_embed(
        C_GREEN, "✅ Ankündigung gesendet",
        fields=[
            {"name": "📺 Kanal",         "value": kanal.mention,  "inline": True},
            {"name": "📝 Interne Notiz", "value": f"> {grund}"},
        ]), ephemeral=True)

# ─────────────────────────────────────────────
#  /svg_rollen_erstellen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="svg_rollen_erstellen",
              description="Erstellt alle 30 SVG-Schadensrollen (2 Tage bis 1 Monat)")
async def cmd_svg_rollen(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await interaction.response.defer()
    names   = [f"{SVG_BASE}{i} Tage" for i in range(2, 31)] + [f"{SVG_BASE}1 Monat"]
    created, skipped, failed = [], [], []

    for name in names:
        if find_role(interaction.guild, name):
            skipped.append(name)
            continue
        try:
            await interaction.guild.create_role(
                name=name, color=discord.Color(INSURANCE_COLOR),
                reason=f"SVG-Rolle erstellt von {interaction.user}")
            created.append(name)
            await asyncio.sleep(0.3)
        except Exception:
            failed.append(name)

    lines = []
    if created: lines.append(f"✅ **Erstellt ({len(created)}):**\n" + "\n".join(f"> `{n}`" for n in created))
    if skipped: lines.append(f"⏭️ **Vorhanden ({len(skipped)}):**\n" + "\n".join(f"> `{n}`" for n in skipped))
    if failed:  lines.append(f"❌ **Fehler ({len(failed)}):**\n"   + "\n".join(f"> `{n}`" for n in failed))

    await interaction.followup.send(embed=make_embed(
        C_GREEN if not failed else C_ORANGE,
        "✅ SVG-Rollen erstellt!" if not failed else "⚠️ SVG-Rollen (mit Fehlern)",
        description="\n\n".join(lines)[:4000],
        fields=[
            {"name": "📋 Gesamt",     "value": f"**{len(names)}**",    "inline": True},
            {"name": "✅ Erstellt",   "value": f"**{len(created)}**",  "inline": True},
            {"name": "⏭️ Übersprungen","value": f"**{len(skipped)}**", "inline": True},
        ], footer=f"Ausgeführt von {interaction.user}"))

# ─────────────────────────────────────────────
#  /lvv_rollen_erstellen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="lvv_rollen_erstellen",
              description="Erstellt alle 30 LVV-Lebensversicherungsrollen (2 Tage bis 1 Monat)")
async def cmd_lvv_rollen(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await interaction.response.defer()
    names   = [f"{LVV_BASE}{i} Tage" for i in range(2, 31)] + [f"{LVV_BASE}1 Monat"]
    created, skipped, failed = [], [], []

    for name in names:
        if find_role(interaction.guild, name):
            skipped.append(name)
            continue
        try:
            await interaction.guild.create_role(
                name=name, color=discord.Color(INSURANCE_COLOR),
                reason=f"LVV-Rolle erstellt von {interaction.user}")
            created.append(name)
            await asyncio.sleep(0.3)
        except Exception:
            failed.append(name)

    lines = []
    if created: lines.append(f"✅ **Erstellt ({len(created)}):**\n" + "\n".join(f"> `{n}`" for n in created))
    if skipped: lines.append(f"⏭️ **Vorhanden ({len(skipped)}):**\n" + "\n".join(f"> `{n}`" for n in skipped))
    if failed:  lines.append(f"❌ **Fehler ({len(failed)}):**\n"   + "\n".join(f"> `{n}`" for n in failed))

    await interaction.followup.send(embed=make_embed(
        C_GREEN if not failed else C_ORANGE,
        "✅ LVV-Rollen erstellt!" if not failed else "⚠️ LVV-Rollen (mit Fehlern)",
        description="\n\n".join(lines)[:4000],
        fields=[
            {"name": "📋 Gesamt",     "value": f"**{len(names)}**",    "inline": True},
            {"name": "✅ Erstellt",   "value": f"**{len(created)}**",  "inline": True},
            {"name": "⏭️ Übersprungen","value": f"**{len(skipped)}**", "inline": True},
        ], footer=f"Ausgeführt von {interaction.user}"))

# ─────────────────────────────────────────────
#  /versicherungsliste  (manual refresh)
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="versicherungsliste",
              description="Aktualisiert die Live-Versicherungsliste sofort manuell")
async def cmd_versicherungsliste(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    await interaction.response.send_message(embed=make_embed(
        C_CYAN, "🔄 Liste wird aktualisiert…"), ephemeral=True)
    await _update_live_list()
    await interaction.edit_original_response(embed=make_embed(
        C_GREEN, "✅ Liste aktualisiert!",
        description="Die Live-Versicherungsliste wurde erfolgreich aktualisiert."))

# ─────────────────────────────────────────────
#  /versicherung_übersicht
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="versicherung_übersicht",
              description="Zeigt alle Versicherungsrollen eines Mitglieds")
@app_commands.describe(mitglied="Das Mitglied (leer = du selbst)")
async def cmd_versicherung_uebersicht(interaction: discord.Interaction,
                                      mitglied: Optional[discord.Member] = None):
    m = mitglied or interaction.user
    svg = [r for r in m.roles if r.name.startswith(SVG_BASE)]
    lvv = [r for r in m.roles if r.name.startswith(LVV_BASE)]

    def fmt_roles(roles: list[discord.Role], prefix: str) -> str:
        if not roles:
            return "*Keine*"
        return "\n".join(f"> {r.name.replace(prefix, '').strip()}" for r in roles)

    await interaction.response.send_message(embed=make_embed(
        C_GREEN, f"📋 Versicherungen von {m.display_name}",
        thumbnail=str(m.display_avatar.url),
        fields=[
            {"name": "🛡️ SVG-Versicherungen", "value": fmt_roles(svg, SVG_BASE)},
            {"name": "💚 LVV-Versicherungen",  "value": fmt_roles(lvv, LVV_BASE)},
            {"name": "📊 Gesamt",
             "value": f"**{len(svg)}** SVG · **{len(lvv)}** LVV", "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /versicherung_kündigen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="versicherung_kündigen",
              description="Entfernt eine Versicherungsrolle von einem Mitglied")
@app_commands.describe(mitglied="Das Mitglied", typ="SVG oder LVV",
                       dauer="Genaue Dauer der Rolle, z.B. '7 Tage' oder '1 Monat'")
@app_commands.choices(typ=[
    app_commands.Choice(name="SVG", value="svg"),
    app_commands.Choice(name="LVV", value="lvv"),
])
async def cmd_versicherung_kuendigen(interaction: discord.Interaction,
                                     mitglied: discord.Member,
                                     typ: str, dauer: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    prefix   = SVG_BASE if typ == "svg" else LVV_BASE
    role_name = f"{prefix}{dauer}"
    role      = find_role(interaction.guild, role_name)

    if not role or role not in mitglied.roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Rolle nicht gefunden",
            f"**{mitglied.display_name}** hat keine Rolle `{role_name}`."), ephemeral=True)

    await mitglied.remove_roles(role, reason=f"Versicherung gekündigt von {interaction.user}")
    await interaction.response.send_message(embed=make_embed(
        C_ORANGE, "❌ Versicherung gekündigt",
        fields=[
            {"name": "👤 Mitglied",  "value": mitglied.mention,          "inline": True},
            {"name": "📄 Typ",       "value": typ.upper(),                "inline": True},
            {"name": "⏱️ Dauer",     "value": dauer,                      "inline": True},
            {"name": "👮 Bearbeitet","value": interaction.user.mention,    "inline": True},
        ]))
    await _update_live_list()

# ─────────────────────────────────────────────
#  /versicherung_verlängern
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="versicherung_verlängern",
              description="Verlängert die Versicherung eines Mitglieds auf eine neue Dauer")
@app_commands.describe(mitglied="Das Mitglied", typ="SVG oder LVV",
                       alte_dauer="Aktuelle Dauer, z.B. '7 Tage'",
                       neue_dauer="Neue Dauer, z.B. '14 Tage' oder '1 Monat'")
@app_commands.choices(typ=[
    app_commands.Choice(name="SVG", value="svg"),
    app_commands.Choice(name="LVV", value="lvv"),
])
async def cmd_versicherung_verlaengern(interaction: discord.Interaction,
                                       mitglied: discord.Member,
                                       typ: str, alte_dauer: str, neue_dauer: str):
    if not interaction.user.guild_permissions.manage_roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    prefix     = SVG_BASE if typ == "svg" else LVV_BASE
    old_role   = find_role(interaction.guild, f"{prefix}{alte_dauer}")
    new_role   = find_role(interaction.guild, f"{prefix}{neue_dauer}")

    if not old_role or old_role not in mitglied.roles:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Alte Rolle nicht gefunden",
            f"**{mitglied.display_name}** hat keine Rolle `{prefix}{alte_dauer}`."), ephemeral=True)
    if not new_role:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Neue Rolle nicht gefunden",
            f"Die Rolle `{prefix}{neue_dauer}` existiert nicht."), ephemeral=True)

    await mitglied.remove_roles(old_role, reason="Versicherung verlängert")
    await mitglied.add_roles(new_role, reason=f"Versicherung verlängert von {interaction.user}")
    await interaction.response.send_message(embed=make_embed(
        C_GREEN, "✅ Versicherung verlängert",
        fields=[
            {"name": "👤 Mitglied",       "value": mitglied.mention,       "inline": True},
            {"name": "📄 Typ",            "value": typ.upper(),             "inline": True},
            {"name": "⏪ Alte Dauer",     "value": alte_dauer,              "inline": True},
            {"name": "⏩ Neue Dauer",     "value": neue_dauer,              "inline": True},
            {"name": "👮 Bearbeitet von", "value": interaction.user.mention,"inline": True},
        ]))
    await _update_live_list()

# ─────────────────────────────────────────────
#  /warn_entfernen
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="warn_entfernen",
              description="Entfernt eine Verwarnung per ID (z.B. W0001)")
@app_commands.describe(mitglied="Das Mitglied", warn_id="Die Warn-ID (z.B. W0001)")
async def cmd_warn_entfernen(interaction: discord.Interaction,
                             mitglied: discord.Member, warn_id: str):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    if remove_warning(str(mitglied.id), warn_id):
        ws = get_warnings(str(mitglied.id))
        await interaction.response.send_message(embed=make_embed(
            C_GREEN, "✅ Verwarnung entfernt",
            fields=[
                {"name": "👤 Mitglied",          "value": mitglied.mention,          "inline": True},
                {"name": "🗑️ Entfernte Warn-ID",  "value": f"`{warn_id.upper()}`",    "inline": True},
                {"name": "📋 Verbleibende Warns", "value": str(len(ws)),              "inline": True},
                {"name": "👮 Entfernt von",       "value": interaction.user.mention,   "inline": True},
            ]))
    else:
        await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Nicht gefunden",
            f"Warn-ID `{warn_id.upper()}` für **{mitglied.display_name}** nicht gefunden."),
            ephemeral=True)

# ─────────────────────────────────────────────
#  /probezeit
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="probezeit",
              description="Setzt ein Mitglied auf Probezeit (Rolle + optionaler Timeout)")
@app_commands.describe(mitglied="Das Mitglied", grund="Grund der Probezeit",
                       tage="Dauer der Probezeit in Tagen (1-30, optional)")
async def cmd_probezeit(interaction: discord.Interaction,
                        mitglied: discord.Member, grund: str,
                        tage: Optional[int] = None):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    probe_role = discord.utils.get(interaction.guild.roles, name="🔰【Probezeit】")
    endet_str  = "*Unbegrenzt*"

    if probe_role:
        await mitglied.add_roles(probe_role, reason=f"Probezeit: {grund}")

    if tage:
        tage = max(1, min(30, tage))
        until = discord.utils.utcnow() + timedelta(days=tage)
        endet_str = f"<t:{int(until.timestamp())}:D>"

    try:
        await mitglied.send(embed=make_embed(
            C_YELLOW, "🔰 Du bist auf Probezeit gesetzt worden",
            description=f"Du wurdest auf dem Server **{interaction.guild.name}** auf Probezeit gesetzt.",
            fields=[
                {"name": "📝 Grund",   "value": f"> {grund}"},
                {"name": "⏳ Endet",   "value": endet_str, "inline": True},
            ],
            footer="Verhalte dich vorbildlich während der Probezeit"))
    except discord.Forbidden:
        pass

    await interaction.response.send_message(embed=make_embed(
        C_YELLOW, "🔰 Probezeit vergeben",
        thumbnail=str(mitglied.display_avatar.url),
        fields=[
            {"name": "👤 Mitglied",  "value": mitglied.mention,          "inline": True},
            {"name": "📝 Grund",     "value": f"> {grund}"},
            {"name": "⏳ Dauer",     "value": endet_str,                  "inline": True},
            {"name": "👮 Moderator", "value": interaction.user.mention,   "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /slow_mode
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="slow_mode",
              description="Setzt den Slow-Mode eines Kanals")
@app_commands.describe(sekunden="Verzögerung in Sekunden (0 = deaktivieren, max 21600)",
                       kanal="Kanal (leer = aktueller Kanal)")
async def cmd_slow_mode(interaction: discord.Interaction,
                        sekunden: int,
                        kanal: Optional[discord.TextChannel] = None):
    if not interaction.user.guild_permissions.manage_channels:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    sek    = max(0, min(21600, sekunden))
    target = kanal or interaction.channel

    await target.edit(slowmode_delay=sek)

    if sek == 0:
        desc = f"Slow-Mode in {target.mention} wurde **deaktiviert**."
        color = C_GREEN
    else:
        h, rem = divmod(sek, 3600)
        m, s   = divmod(rem, 60)
        parts  = []
        if h: parts.append(f"{h}h")
        if m: parts.append(f"{m}m")
        if s: parts.append(f"{s}s")
        desc  = f"Slow-Mode in {target.mention} auf **{''.join(parts)}** gesetzt."
        color = C_ORANGE

    await interaction.response.send_message(embed=make_embed(
        color, "🐢 Slow-Mode aktualisiert", description=desc,
        fields=[{"name": "👮 Gesetzt von", "value": interaction.user.mention, "inline": True}]))

# ─────────────────────────────────────────────
#  /umfrage
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="umfrage",
              description="Erstellt eine einfache Ja/Nein-Umfrage")
@app_commands.describe(frage="Die Frage der Umfrage",
                       option_a="Option A (Standard: Ja)",
                       option_b="Option B (Standard: Nein)")
async def cmd_umfrage(interaction: discord.Interaction, frage: str,
                      option_a: str = "Ja", option_b: str = "Nein"):
    embed = discord.Embed(
        title="📊 Umfrage",
        description=f"**{frage}**",
        color=C_BLUE,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="🟢 A", value=option_a, inline=True)
    embed.add_field(name="🔴 B", value=option_b, inline=True)
    embed.set_footer(text=f"Gestartet von {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("🟢")
    await msg.add_reaction("🔴")
    await msg.add_reaction("🤷")

# ─────────────────────────────────────────────
#  /rolle_info
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="rolle_info",
              description="Zeigt alle Mitglieder einer Rolle")
@app_commands.describe(rolle="Die Rolle, deren Mitglieder angezeigt werden sollen")
async def cmd_rolle_info(interaction: discord.Interaction, rolle: discord.Role):
    members = rolle.members
    if not members:
        return await interaction.response.send_message(embed=make_embed(
            C_YELLOW, f"ℹ️ {rolle.name}",
            description="*Kein Mitglied hat diese Rolle.*"))

    chunks   = [members[i:i+20] for i in range(0, len(members), 20)]
    lines    = "\n".join(f"> {m.mention} — `{m.id}`" for m in chunks[0])
    overflow = f"\n*…und {len(members) - 20} weitere*" if len(members) > 20 else ""

    await interaction.response.send_message(embed=make_embed(
        rolle.color.value if rolle.color.value else C_BLUE,
        f"👥 {rolle.name}",
        fields=[
            {"name": f"Mitglieder ({len(members)})", "value": lines[:1020] + overflow},
            {"name": "🎨 Farbe",   "value": str(rolle.color),      "inline": True},
            {"name": "📌 Position","value": str(rolle.position),    "inline": True},
            {"name": "🔖 ID",      "value": f"`{rolle.id}`",        "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /bot_info
# ─────────────────────────────────────────────
@tree.command(guild=GUILD, name="bot_info",
              description="Zeigt Status und Statistiken des Bots")
async def cmd_bot_info(interaction: discord.Interaction):
    guild  = interaction.guild
    latenz = round(bot.latency * 1000)
    color  = C_GREEN if latenz < 100 else (C_YELLOW if latenz < 250 else C_RED)

    await interaction.response.send_message(embed=make_embed(
        color, "🤖 Bot-Informationen",
        thumbnail=str(bot.user.display_avatar.url),
        fields=[
            {"name": "🏓 Latenz",        "value": f"**{latenz} ms**",           "inline": True},
            {"name": "🌐 Server",         "value": guild.name,                   "inline": True},
            {"name": "👥 Mitglieder",     "value": str(guild.member_count),      "inline": True},
            {"name": "📋 Rollen gesamt",  "value": str(len(guild.roles)),        "inline": True},
            {"name": "💬 Kanäle",         "value": str(len(guild.channels)),     "inline": True},
            {"name": "🆔 Bot-ID",         "value": f"`{bot.user.id}`",           "inline": True},
            {"name": "⚠️ Aktive Warns",
             "value": str(sum(len(v) for v in warnings_store.values())),          "inline": True},
        ]))

# ─────────────────────────────────────────────
#  /notiz
# ─────────────────────────────────────────────
notes_store: dict[str, list[dict]] = {}

@tree.command(guild=GUILD, name="notiz",
              description="Fügt eine Notiz zu einem Mitglied hinzu oder zeigt alle an")
@app_commands.describe(mitglied="Das Mitglied",
                       text="Notiztext (leer lassen zum Anzeigen aller Notizen)")
async def cmd_notiz(interaction: discord.Interaction,
                    mitglied: discord.Member, text: Optional[str] = None):
    if not interaction.user.guild_permissions.moderate_members:
        return await interaction.response.send_message(embed=make_embed(
            C_RED, "❌ Keine Berechtigung"), ephemeral=True)

    uid = str(mitglied.id)

    if text:
        entry = {
            "text": text,
            "mod": str(interaction.user),
            "ts": datetime.now(timezone.utc)
        }
        notes_store.setdefault(uid, []).append(entry)
        count = len(notes_store[uid])
        await interaction.response.send_message(embed=make_embed(
            C_CYAN, "📝 Notiz hinzugefügt",
            fields=[
                {"name": "👤 Mitglied",     "value": mitglied.mention,          "inline": True},
                {"name": "📋 Notiz #",      "value": str(count),                "inline": True},
                {"name": "📝 Text",         "value": f"> {text}"},
                {"name": "👮 Hinzugefügt",  "value": interaction.user.mention,  "inline": True},
            ]), ephemeral=True)
    else:
        notes = notes_store.get(uid, [])
        if not notes:
            return await interaction.response.send_message(embed=make_embed(
                C_YELLOW, f"📝 Notizen: {mitglied.display_name}",
                description="*Keine Notizen vorhanden.*"), ephemeral=True)

        lines = "\n".join(
            f"**#{i+1}** `{n['ts'].strftime('%d.%m.%Y')}` — {n['text']}"
            for i, n in enumerate(notes[-10:])
        )
        await interaction.response.send_message(embed=make_embed(
            C_CYAN, f"📝 Notizen: {mitglied.display_name}",
            description=lines[:2000],
            thumbnail=str(mitglied.display_avatar.url),
            fields=[{"name": "📊 Gesamt", "value": str(len(notes)), "inline": True}]
        ), ephemeral=True)

# ─────────────────────────────────────────────
#  LIVE LIST LOGIC
# ─────────────────────────────────────────────
def _duration_sort_key(role_name: str, prefix: str) -> int:
    suffix = role_name.replace(prefix, "").strip()
    try:
        return DURATION_ORDER.index(suffix)
    except ValueError:
        return 999

async def _update_live_list():
    global live_message_id
    try:
        guild = bot.get_guild(GUILD_ID)
        if not guild:
            print(f"[LiveList] ❌ Guild {GUILD_ID} nicht gefunden")
            return

        # Fetch channel directly — don't rely on cache
        try:
            channel = await bot.fetch_channel(LIVE_LIST_CHANNEL_ID)
        except Exception as e:
            print(f"[LiveList] ❌ Kanal {LIVE_LIST_CHANNEL_ID} nicht gefunden: {e}")
            return

        if not isinstance(channel, discord.TextChannel):
            print(f"[LiveList] ❌ Kanal ist kein Textkanal")
            return

        # If guild is not chunked yet, request members now (requires Server Members Intent)
        if not guild.chunked:
            try:
                await asyncio.wait_for(guild.chunk(cache=True), timeout=15.0)
                print(f"[LiveList] ✅ Guild gecacht — {guild.member_count} Mitglieder", flush=True)
            except asyncio.TimeoutError:
                print("[LiveList] ⚠️ Chunk-Timeout — versuche fetch_members()...", flush=True)
                # Fallback: manually populate cache via REST
                try:
                    async for member in guild.fetch_members(limit=None):
                        pass  # discord.py caches each member as it's yielded
                    print(f"[LiveList] ✅ Mitglieder via REST geholt", flush=True)
                except Exception as fe:
                    print(f"[LiveList] ⚠️ fetch_members Fehler: {fe}", flush=True)
            except Exception as e:
                print(f"[LiveList] ⚠️ chunk() Fehler: {e}", flush=True)
        else:
            print(f"[LiveList] ✅ Guild bereits gecacht — {guild.member_count} Mitglieder", flush=True)

        # Collect insurance roles
        svg_roles = sorted(
            [r for r in guild.roles if r.name.startswith(SVG_BASE)],
            key=lambda r: _duration_sort_key(r.name, SVG_BASE)
        )
        lvv_roles = sorted(
            [r for r in guild.roles if r.name.startswith(LVV_BASE)],
            key=lambda r: _duration_sort_key(r.name, LVV_BASE)
        )

        print(f"[LiveList] SVG-Rollen: {len(svg_roles)}, LVV-Rollen: {len(lvv_roles)}")

        def build_fields(roles: list[discord.Role], prefix: str):
            fields, total = [], 0
            for role in roles:
                if not role.members:
                    continue
                lines = "\n".join(
                    f"> **{m.display_name}** — `{m.id}`" for m in role.members
                )
                fields.append({
                    "name": f"{role.name.replace(prefix, '').strip()} ({len(role.members)})",
                    "value": lines[:1020],
                    "inline": False
                })
                total += len(role.members)
            return fields, total

        svg_fields, svg_total = build_fields(svg_roles, SVG_BASE)
        lvv_fields, lvv_total = build_fields(lvv_roles, LVV_BASE)
        now_ts = int(discord.utils.utcnow().timestamp())

        header_embed = discord.Embed(
            title="📋 Versicherungs-Live-Liste",
            description=(
                f"Alle aktiven Versicherungsrollen auf dem Server.\n"
                f"🕐 Zuletzt aktualisiert: <t:{now_ts}:R>"
            ),
            color=INSURANCE_COLOR,
            timestamp=discord.utils.utcnow()
        )
        header_embed.add_field(name="📊 SVG gesamt", value=f"**{svg_total}** Mitglieder", inline=True)
        header_embed.add_field(name="📊 LVV gesamt", value=f"**{lvv_total}** Mitglieder", inline=True)

        svg_embed = discord.Embed(title="🛡️ SVG｜Schaden versichert", color=INSURANCE_COLOR)
        if svg_fields:
            for f in svg_fields[:25]:
                svg_embed.add_field(name=f["name"], value=f["value"], inline=False)
        else:
            svg_embed.description = "*Keine aktiven SVG-Versicherungen*"

        lvv_embed = discord.Embed(title="💚 LVV｜Leben versichert", color=INSURANCE_COLOR)
        if lvv_fields:
            for f in lvv_fields[:25]:
                lvv_embed.add_field(name=f["name"], value=f["value"], inline=False)
        else:
            lvv_embed.description = "*Keine aktiven LVV-Versicherungen*"

        all_embeds = [header_embed, svg_embed, lvv_embed]

        # Try to edit existing message
        if live_message_id:
            try:
                msg = await channel.fetch_message(live_message_id)
                await msg.edit(embeds=all_embeds)
                print(f"[LiveList] ✅ Nachricht aktualisiert (ID: {live_message_id})")
                return
            except discord.NotFound:
                live_message_id = None

        # Search for existing bot message in channel
        async for msg in channel.history(limit=30):
            if (msg.author.id == bot.user.id
                    and msg.embeds
                    and msg.embeds[0].title == "📋 Versicherungs-Live-Liste"):
                live_message_id = msg.id
                await msg.edit(embeds=all_embeds)
                print(f"[LiveList] ✅ Vorhandene Nachricht aktualisiert (ID: {live_message_id})")
                return

        # Post new message
        sent = await channel.send(embeds=all_embeds)
        live_message_id = sent.id
        print(f"[LiveList] ✅ Neue Nachricht gesendet (ID: {live_message_id})")

    except Exception as e:
        print(f"[LiveList] ❌ Unbekannter Fehler: {e}")
        import traceback
        traceback.print_exc()

@tasks.loop(minutes=2)
async def live_list_task():
    await _update_live_list()

@live_list_task.before_loop
async def before_live_list():
    await bot.wait_until_ready()

# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    await tree.sync(guild=GUILD)
    print(f"✅ Bot ist bereit: {bot.user} | Guilds: {len(bot.guilds)}", flush=True)
    print(f"✅ Slash-Commands synchronisiert für Guild {GUILD_ID}", flush=True)
    # Run live list immediately on startup
    await _update_live_list()
    # Then keep updating every 2 minutes
    if not live_list_task.is_running():
        live_list_task.start()

# ─────────────────────────────────────────────
#  START
# ─────────────────────────────────────────────
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN ist nicht gesetzt!")

bot.run(TOKEN)

