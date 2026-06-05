# Discord Bot Intents Setup Guide

## Why Intents Are Required

Discord requires bots to explicitly request "privileged intents" to access certain types of data. Our bot needs these intents to function properly.

## Required Intents

### MESSAGE CONTENT INTENT (Required)

**Why:** The bot needs to read message content in ticket channels to relay them to the backend API.

**How to Enable:**
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Select your bot application
3. Click **Bot** in the left sidebar
4. Scroll down to **Privileged Gateway Intents** section
5. Toggle **MESSAGE CONTENT INTENT** to ON (green)
6. Click **Save Changes** at the bottom
7. Wait 1-2 minutes for changes to propagate

**Visual Guide:**
```
Discord Developer Portal
  └─ Your Application
      └─ Bot (left sidebar)
          └─ Scroll down to "Privileged Gateway Intents"
              └─ [✓] MESSAGE CONTENT INTENT  ← Enable this!
```

## Optional Intents (For Future Features)

### SERVER MEMBERS INTENT (Optional)

**Why:** May be needed for future features like user management or advanced permissions.

**How to Enable:** Same process as above, toggle **SERVER MEMBERS INTENT**

## Verification

After enabling intents:

1. **Wait 1-2 minutes** for Discord to propagate changes
2. **Restart your bot**
3. Check bot logs - you should see:
   ```
   [BOT] INFO - Bot logged in as YourBotName (ID: 123456789)
   [BOT] INFO - Connected to X guild(s)
   ```

If you still see `PrivilegedIntentsRequired` error:
- Double-check the intent is enabled and saved
- Wait a few more minutes
- Try restarting the bot again

## Troubleshooting

### Error: "PrivilegedIntentsRequired"

**Cause:** Intents not enabled or changes not yet propagated

**Solutions:**
1. Verify intent is enabled in Developer Portal
2. Wait 2-3 minutes after enabling
3. Restart the bot
4. Check bot logs for detailed error message

### Bot Can't Read Messages

**Cause:** MESSAGE CONTENT INTENT not enabled

**Solution:** Enable MESSAGE CONTENT INTENT (see above)

### Intent Option Not Visible

**Cause:** Your bot account may be too new or have restrictions

**Solution:**
- Make sure your bot is verified in the Developer Portal
- Some intents require bot verification for larger servers
- For testing, intents should be available immediately

## Important Notes

- **Intents are required** - The bot will NOT work without MESSAGE CONTENT INTENT
- **Changes take time** - Wait 1-2 minutes after enabling before restarting
- **One-time setup** - Once enabled, you don't need to do this again
- **Security** - Only enable intents you actually need

## Need Help?

If you're still having issues:
1. Check the bot logs for specific error messages
2. Verify your bot token is correct in `.env`
3. Make sure you're using the correct application in Developer Portal
4. Try disabling and re-enabling the intent

