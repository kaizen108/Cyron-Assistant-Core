"""Panel view — handles panel button clicks and ticket creation."""

import logging
import time
import discord
from discord import ui

from bot.utils.http_client import get_client
from bot.utils.placeholders import resolve_placeholders
from bot.utils.support_hours import is_support_open
from bot.utils.ticket_logger import log_ticket_event

logger = logging.getLogger(__name__)

BUTTON_STYLES = {
    "blurple": discord.ButtonStyle.primary,
    "green":   discord.ButtonStyle.success,
    "red":     discord.ButtonStyle.danger,
    "grey":    discord.ButtonStyle.secondary,
    "gray":    discord.ButtonStyle.secondary,
}

# In-memory cooldown tracker: {guild_id: {user_id: timestamp}}
_cooldowns: dict[int, dict[int, float]] = {}


def build_panel_embed(panel: dict) -> discord.Embed:
    color_hex = panel.get("panel_embed_color") or "#5865F2"
    try:
        color = discord.Colour(int(color_hex.lstrip("#"), 16))
    except Exception:
        color = discord.Colour.blurple()

    embed = discord.Embed(
        title=panel.get("panel_embed_title") or "Create a ticket",
        description=panel.get("panel_embed_description") or "Click the button below to open a support ticket.",
        color=color,
    )
    if panel.get("panel_embed_author"):
        embed.set_author(name=panel["panel_embed_author"])
    if panel.get("panel_embed_footer"):
        embed.set_footer(text=panel["panel_embed_footer"])
    return embed


class PanelView(ui.View):
    """Persistent view with the Open Ticket button for a panel."""

    def __init__(self, panel: dict) -> None:
        super().__init__(timeout=None)
        style = BUTTON_STYLES.get(panel.get("button_color", "blurple"), discord.ButtonStyle.primary)
        btn = ui.Button(
            label=panel.get("button_text") or "Open Ticket",
            emoji=panel.get("button_emoji") or None,
            style=style,
            custom_id=f"panel_open:{panel['id']}",
        )
        btn.callback = self._open_callback
        self.add_item(btn)

    async def _open_callback(self, interaction: discord.Interaction) -> None:
        await handle_panel_button(interaction)


async def handle_panel_button(interaction: discord.Interaction) -> None:
    """Full ticket creation flow triggered by panel button click."""
    custom_id = (interaction.data or {}).get("custom_id", "")
    if not custom_id.startswith("panel_open:"):
        return

    panel_id = custom_id.split(":", 1)[1]
    guild = interaction.guild
    member = interaction.user

    if not guild or not isinstance(member, discord.Member):
        await interaction.response.send_message("This can only be used in a server.", ephemeral=True)
        return

    client = get_client()
    panel = await client.get_panel(str(guild.id), panel_id)
    if not panel:
        await interaction.response.send_message("Panel not found.", ephemeral=True)
        return

    if not panel.get("is_enabled", True):
        await interaction.response.send_message("This panel is currently disabled.", ephemeral=True)
        return

    # Support hours check
    is_open, state = is_support_open(panel)
    if not is_open:
        if panel.get("closed_state_logic") == "deny_creation":
            msg_data = panel.get("msg_closed") or {}
            msg = msg_data.get("description") or "Support is currently closed. Please try again during support hours."
            await interaction.response.send_message(msg, ephemeral=True)
            return
        # allow_with_warning — continue but warn after creation

    # Role checks
    member_role_ids = {r.id for r in member.roles}
    required = panel.get("roles_required") or []
    if required and not any(int(r) in member_role_ids for r in required):
        await interaction.response.send_message("You don't have the required role to open a ticket.", ephemeral=True)
        return

    blocked = panel.get("roles_blocked") or []
    if any(int(r) in member_role_ids for r in blocked):
        await interaction.response.send_message("You are not allowed to open a ticket.", ephemeral=True)
        return

    # Cooldown check
    cooldown_secs = panel.get("creation_cooldown_seconds", 0)
    if cooldown_secs > 0:
        guild_cooldowns = _cooldowns.setdefault(guild.id, {})
        last = guild_cooldowns.get(member.id, 0)
        elapsed = time.time() - last
        if elapsed < cooldown_secs:
            remaining = int(cooldown_secs - elapsed)
            await interaction.response.send_message(
                f"Please wait {remaining}s before opening another ticket.", ephemeral=True
            )
            return

    # Max open tickets check
    max_tickets = panel.get("max_open_tickets_per_user", 1)
    open_tickets = await client.get_open_tickets_by_user(str(guild.id), str(member.id))
    # Filter to this panel
    panel_open = [t for t in open_tickets]
    if len(panel_open) >= max_tickets:
        # Find existing channel
        existing_channel_id = panel_open[0].get("channel_id") if panel_open else None
        msg = "You already have an open ticket."
        if existing_channel_id:
            ch = guild.get_channel(int(existing_channel_id))
            if ch:
                msg = f"You already have an open ticket: {ch.mention}"
        await interaction.response.send_message(msg, ephemeral=True)
        return

    # Forms check
    if panel.get("forms_enabled") and panel.get("form_questions"):
        modal = DynamicTicketModal(panel, member)
        await interaction.response.send_modal(modal)
        return

    # Create ticket directly
    await interaction.response.defer(ephemeral=True)
    await create_ticket_channel(interaction, panel, member, form_answers=None)

    # Out-of-hours warning (after creation)
    if not is_open and panel.get("closed_state_logic") == "allow_with_warning":
        try:
            await interaction.followup.send(
                "⚠️ Support is currently outside normal hours. Response times may be delayed.",
                ephemeral=True,
            )
        except Exception:
            pass


class DynamicTicketModal(ui.Modal):
    def __init__(self, panel: dict, member: discord.Member) -> None:
        super().__init__(title=f"Open Ticket — {panel['name'][:40]}", custom_id=f"ticket_form:{panel['id']}")
        self.panel = panel
        self.member = member

        questions = sorted(panel.get("form_questions") or [], key=lambda q: q.get("order", 0))
        for q in questions[:5]:
            style = discord.TextStyle.paragraph if q.get("answer_type") == "multiline" else discord.TextStyle.short
            self.add_item(ui.TextInput(
                label=q["label"][:45],
                style=style,
                placeholder=q.get("placeholder", "")[:100] or None,
                required=q.get("required", True),
                min_length=q.get("min_length", 0),
                max_length=q.get("max_length", 500),
                custom_id=q["id"],
            ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        answers = {child.custom_id: child.value for child in self.children}
        await interaction.response.defer(ephemeral=True)
        await create_ticket_channel(interaction, self.panel, self.member, form_answers=answers)


async def create_ticket_channel(
    interaction: discord.Interaction,
    panel: dict,
    member: discord.Member,
    form_answers: dict | None,
) -> None:
    guild = interaction.guild
    client = get_client()

    # Get next ticket number
    ticket_number = await client.next_ticket_number(str(guild.id))

    # Resolve channel name
    fmt = panel.get("channel_name_format") or "{panel.name}-{ticket.number}"
    ctx = {
        "panel_name": panel["name"].lower().replace(" ", "-"),
        "creator_username": member.name.lower(),
        "ticket_number": str(ticket_number).zfill(4),
        "guild_name": guild.name,
    }
    channel_name = fmt
    for k, v in {
        "{panel.name}": ctx["panel_name"],
        "{ticket.creator.username}": ctx["creator_username"],
        "{ticket.number}": ctx["ticket_number"],
    }.items():
        channel_name = channel_name.replace(k, v)
    channel_name = channel_name[:100]

    # Find category
    category_name = panel.get("ticket_category_name") or "Tickets"
    category = discord.utils.get(guild.categories, name=category_name)
    if category and len(category.channels) >= 50:
        # Try overflow
        for oc_id in (panel.get("overflow_category_ids") or []):
            oc = guild.get_channel(int(oc_id))
            if oc and isinstance(oc, discord.CategoryChannel) and len(oc.channels) < 50:
                category = oc
                break

    # Build permission overwrites
    overwrites: dict = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True, manage_channels=True),
    }
    for role_id in (panel.get("support_role_ids") or []):
        role = guild.get_role(int(role_id))
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

    try:
        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket #{ticket_number} by {member}",
        )
    except Exception as e:
        logger.error("Failed to create ticket channel: %s", e)
        try:
            await interaction.followup.send("❌ Failed to create ticket channel. Check bot permissions.", ephemeral=True)
        except Exception:
            pass
        return

    # Record cooldown
    _cooldowns.setdefault(guild.id, {})[member.id] = time.time()

    # Register in backend
    await client.open_ticket(
        guild_id=str(guild.id),
        channel_id=ticket_channel.id,
        user_id=member.id,
        panel_id=panel["id"],
        bot_id=guild.me.id,
        ticket_number=ticket_number,
        channel_name=channel_name,
        form_answers=form_answers,
    )

    # Build welcome embed
    placeholder_ctx = {
        "creator_mention": member.mention,
        "creator_username": member.name,
        "ticket_number": str(ticket_number).zfill(4),
        "channel_mention": ticket_channel.mention,
        "panel_name": panel["name"],
        "guild_name": guild.name,
    }

    welcome_desc = resolve_placeholders(
        panel.get("welcome_embed_description") or
        f"Welcome {member.mention}! Please describe your issue and we'll get back to you.",
        placeholder_ctx,
    )
    try:
        color = discord.Colour(int((panel.get("panel_embed_color") or "#5865F2").lstrip("#"), 16))
    except Exception:
        color = discord.Colour.blurple()

    welcome_embed = discord.Embed(
        title=panel.get("welcome_embed_title") or "Ticket Created",
        description=welcome_desc,
        color=color,
    )
    if panel.get("welcome_embed_author"):
        welcome_embed.set_author(name=resolve_placeholders(panel["welcome_embed_author"], placeholder_ctx))
    if panel.get("welcome_embed_footer"):
        welcome_embed.set_footer(text=resolve_placeholders(panel["welcome_embed_footer"], placeholder_ctx))
    if panel.get("footer_text"):
        welcome_embed.set_footer(text=resolve_placeholders(panel["footer_text"], placeholder_ctx))

    # Build pings
    pings = []
    if panel.get("welcome_ping_ticket_creator"):
        pings.append(member.mention)
    if panel.get("welcome_ping_support_roles"):
        for role_id in (panel.get("support_role_ids") or []):
            role = guild.get_role(int(role_id))
            if role:
                pings.append(role.mention)

    ping_content = " ".join(pings) if pings else None

    # Build ticket view buttons
    from bot.views.ticket_view import TicketView
    close_label = panel.get("close_button_label") or "Close"
    close_emoji = panel.get("close_button_emoji") or "🔒"
    claim_label = panel.get("claim_button_label") or "Claim"
    claim_emoji = panel.get("claim_button_emoji") or "👤"
    claiming_enabled = panel.get("claiming_enabled", True)

    view = TicketView(
        ticket_channel.id,
        timeout=None,
        close_label=close_label,
        close_emoji=close_emoji,
        claim_label=claim_label,
        claim_emoji=claim_emoji,
        claiming_enabled=claiming_enabled,
    )

    welcome_msg = await ticket_channel.send(content=ping_content, embed=welcome_embed, view=view)

    if panel.get("auto_pin_welcome"):
        try:
            await welcome_msg.pin()
        except Exception:
            pass

    # Send form answers embed if any
    if form_answers and panel.get("form_questions"):
        questions = {q["id"]: q["label"] for q in (panel.get("form_questions") or [])}
        answers_embed = discord.Embed(title="📋 Ticket Information", color=color)
        for qid, answer in form_answers.items():
            label = questions.get(qid, qid)
            answers_embed.add_field(name=label, value=answer or "—", inline=False)
        await ticket_channel.send(embed=answers_embed)

    # Log event
    try:
        await log_ticket_event(
            bot=guild._state._get_client(),
            guild=guild,
            event_type="TICKET_OPENED",
            channel=ticket_channel,
            actor=member,
            panel=panel,
        )
    except Exception as e:
        logger.debug("log_ticket_event failed: %s", e)

    # Reply to user
    try:
        await interaction.followup.send(f"✅ Ticket created: {ticket_channel.mention}", ephemeral=True)
    except Exception:
        pass
