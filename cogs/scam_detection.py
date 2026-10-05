import asyncio
import hashlib
import io
import os
import traceback

import aiohttp
import fluxer
import pytesseract
from Levenshtein import distance
from PIL import Image

import db
from framework import BlanketCog, Context
from utils import utcnow

SCAM_WORDS = "withdraw claim reward casino crypto mrbeast promo special cryptocurrency vip bonus redeem receive coin deleted wallet celebrate register transferred promotion chance money winner successful block explorer deposit".split()
SCAM_MUTE_DURATION = "10m"
TRIGGER_LEVEL = 120
HASH_FILE = os.path.join(os.path.dirname(os.path.abspath(os.getenv("DB_PATH", "bot.db"))), "scam_hashes.txt")

known_hashes: set[str] = set()


def _load_hashes():
    try:
        with open(HASH_FILE) as f: return set(f.read().splitlines())
    except FileNotFoundError: return set()


def _save_hashes(new: set[str]):
    known_hashes.update(new)
    with open(HASH_FILE, "a") as f:
        for h in new: f.write(h + "\n")


def _lev_threshold(word: str) -> int:
    return max(0, (len(word) - 4) // 3)


class ScamDetection(BlanketCog):
    async def cog_load(self):
        global known_hashes
        known_hashes = _load_hashes()
        print(f"[scam] loaded {len(known_hashes)} known hashes | hash file: {HASH_FILE}")

    def _log_channel_id(self, guild_id):
        settings = db.get_guild_settings(guild_id)
        return (settings and settings["log_channel"]) or int(os.getenv("LOG_CHANNEL_ID", 0))

    async def _download_all(self, images) -> list[bytes]:
        async with aiohttp.ClientSession() as session:
            async def fetch(att):
                async with session.get(att.url) as resp:
                    return await resp.read()
            return await asyncio.gather(*[fetch(a) for a in images])

    async def _run_ocr(self, message, image_data: list[bytes]):
        image_hashes, matches, all_text, scam_images = [], {}, "", set()

        for i, data in enumerate(image_data):
            h = hashlib.sha256(data).hexdigest()
            image_hashes.append(h)

            if h in known_hashes:
                embed = fluxer.Embed(title="Recognized Scam Hash", color=0xd42c03)
                embed.description = f"Deleted message in <#{message.channel_id}> by {message.author.mention}"
                return True, embed, i + 1, scam_images

            try:
                text = (await asyncio.to_thread(pytesseract.image_to_string, Image.open(io.BytesIO(data)))).strip()
            except pytesseract.TesseractError:
                continue
            except OSError:
                print("[scam] tesseract-ocr not installed")
                return False, None, i + 1, scam_images
            if not text: continue

            all_text += text + " "

            img_matches = {}
            for sw in SCAM_WORDS:
                c = sum(1 for w in text.lower().split() if distance(w, sw) <= _lev_threshold(sw))
                if c: img_matches[sw] = c
            if len(img_matches) >= 3:
                scam_images.add(h)

            matches = {}
            for sw in SCAM_WORDS:
                c = sum(1 for w in all_text.lower().split() if distance(w, sw) <= _lev_threshold(sw))
                if c: matches[sw] = c
            if len(matches) < 3: continue

            confidence = len(matches) * sum(matches.values())
            if confidence >= TRIGGER_LEVEL:
                _save_hashes({h for h in scam_images if h not in known_hashes})
                match_list = ", ".join(f"{w} (x{c})" for w, c in matches.items())
                embed = fluxer.Embed(title="Scam Message Detected", color=0xf7b200)
                embed.description = f"Deleted message in <#{message.channel_id}> by {message.author.mention}"
                embed.add_field(name="Likelihood coefficient", value=f"{confidence} after {i + 1} image{'s' if i else ''}", inline=True)
                embed.add_field(name="Matches", value=match_list, inline=False)
                return True, embed, i + 1, scam_images

        return False, None, len(image_data), set()

    async def _cache_remaining(self, image_data: list[bytes], start_idx: int, scam_images: set[str]):
        for data in image_data[start_idx:]:
            h = hashlib.sha256(data).hexdigest()
            if h in known_hashes: continue
            try:
                text = (await asyncio.to_thread(pytesseract.image_to_string, Image.open(io.BytesIO(data)))).strip()
            except: continue
            if not text: continue
            img_matches = {}
            for sw in SCAM_WORDS:
                c = sum(1 for w in text.lower().split() if distance(w, sw) <= _lev_threshold(sw))
                if c: img_matches[sw] = c
            if len(img_matches) >= 3:
                scam_images.add(h)
        _save_hashes({h for h in scam_images if h not in known_hashes})

    async def _mute_scammer(self, message, guild_id):
        moderation = self.bot._cogs.get("Moderation")
        member = await self.bot.member(guild_id, message.author.id)
        if moderation is None or member is None:
            return
        ctx = Context(self.bot, message, guild_id, None)
        ctx.author = self.bot.user  # cases are logged as the bot
        try:
            result = await moderation._mute(ctx, member, SCAM_MUTE_DURATION, "Automod: scam image")
            print(f"[scam] mute result: {result}")
        except fluxer.HTTPException as e:
            print(f"[scam] mute failed: {e}")

    @fluxer.Cog.listener()
    async def on_message(self, message):
        try:
            if message.author.bot: return
            images = [a for a in message.attachments if a.content_type and a.content_type.startswith("image/")]
            if not images: return
            guild_id = await self.bot.guild_id_of(message)
            if not guild_id: return

            image_data = await self._download_all(images)
            is_scam, embed, processed_count, scam_images = await self._run_ocr(message, image_data)
            if not is_scam: return

            await self._mute_scammer(message, guild_id)

            log_channel_id = self._log_channel_id(guild_id)

            try: await message.delete()
            except fluxer.HTTPException: pass

            processing_time = int((utcnow() - message.created_at).total_seconds() * 1000)
            embed.set_footer(text=f"Processing time: {processing_time}ms")
            if log_channel_id:
                # fluxer.py has no message forwarding, so the images are re-uploaded instead
                files = [fluxer.File(io.BytesIO(raw), filename=att.filename) for raw, att in zip(image_data, images)]
                try:
                    await self.bot.http.send_message(
                        log_channel_id, embeds=[embed], files=[f.to_dict() for f in files],
                    )
                except fluxer.HTTPException as e:
                    print(f"[scam] couldn't post to log channel: {e}")

            if processed_count < len(image_data):
                asyncio.create_task(self._cache_remaining(image_data, processed_count, scam_images))

        except Exception:
            print(f"[scam] error:\n{traceback.format_exc()}")


async def setup(bot):
    await bot.add_cog(ScamDetection(bot))