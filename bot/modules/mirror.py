from base64 import b64encode
from requests import utils as rutils, get as rget
from re import match as re_match, search as re_search, split as re_split
from time import sleep, time
from os import path as ospath, remove as osremove, listdir, walk
from shutil import rmtree
from threading import Thread
from subprocess import run as srun
from pathlib import PurePath
from html import escape
from telegram.ext import CommandHandler
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ParseMode
from bot import bot, Interval, INDEX_URL, BUTTON_FOUR_NAME, BUTTON_FOUR_URL, BUTTON_FIVE_NAME, BUTTON_FIVE_URL, \
                BUTTON_SIX_NAME, BUTTON_SIX_URL, VIEW_LINK, aria2, dispatcher, DOWNLOAD_DIR, \
                download_dict, download_dict_lock, MAX_LEECH_SIZE, LOGGER, DB_URI, INCOMPLETE_TASK_NOTIFIER, \
                LEECH_LOG, SOURCE_LINK, BOT_PM, MIRROR_LOGS, AUTO_DELETE_UPLOAD_MESSAGE_DURATION, MEGA_API_KEY
from bot.helper.ext_utils.bot_utils import is_url, is_magnet, is_gdtot_link, is_mega_link, is_gdrive_link, get_content_type
from bot.helper.ext_utils.fs_utils import get_base_name, get_path_size, split_file, clean_download
from bot.helper.ext_utils.exceptions import DirectDownloadLinkException, NotSupportedExtractionArchive
from bot.helper.mirror_utils.download_utils.aria2_download import add_aria2c_download
from bot.helper.mirror_utils.download_utils.gd_downloader import add_gd_download
from bot.helper.mirror_utils.download_utils.qbit_downloader import QbDownloader
from bot.helper.mirror_utils.download_utils.mega_downloader import MegaDownloader
from bot.helper.mirror_utils.download_utils.direct_link_generator import direct_link_generator
from bot.helper.mirror_utils.download_utils.telegram_downloader import TelegramDownloadHelper
from bot.helper.mirror_utils.status_utils.extract_status import ExtractStatus
from bot.helper.mirror_utils.status_utils.zip_status import ZipStatus
from bot.helper.mirror_utils.status_utils.split_status import SplitStatus
from bot.helper.mirror_utils.status_utils.upload_status import UploadStatus
from bot.helper.mirror_utils.status_utils.tg_upload_status import TgUploadStatus
from bot.helper.mirror_utils.upload_utils.gdriveTools import GoogleDriveHelper
from bot.helper.mirror_utils.upload_utils.pyrogramEngine import TgUploader
from bot.helper.telegram_helper.bot_commands import BotCommands
from bot.helper.telegram_helper.filters import CustomFilters
from bot.helper.telegram_helper.message_utils import sendMessage, sendMarkup, delete_all_messages, update_all_messages, \
                                                        auto_delete_message, auto_delete_upload_message
from bot.helper.telegram_helper.button_build import ButtonMaker
from bot.helper.ext_utils.db_handler import DbManger
from bot.helper.ext_utils.telegraph_helper import telegraph
from pyshorteners import Shortener

def get_shortlink(url):
   shortlink = False 
   try:
      shortlink = Shortener().dagd.short(url)
   except Exception as err:
       print(err)
       pass
   return shortlink

class MirrorListener:
    def __init__(self, bot, message, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None, tag=None):
        self.bot = bot
        self.message = message
        self.uid = self.message.message_id
        self.extract = extract
        self.isZip = isZip
        self.isQbit = isQbit
        self.isLeech = isLeech
        self.pswd = pswd
        self.tag = tag
        self.isPrivate = self.message.chat.type in ['private', 'group']
        self.user_id = self.message.from_user.id
        reply_to = self.message.reply_to_message

    def clean(self):
        try:
            aria2.purge()
            Interval[0].cancel()
            del Interval[0]
            delete_all_messages()
        except IndexError:
            pass

    def onDownloadStart(self):
        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().add_incomplete_task(self.message.chat.id, self.message.link, self.tag)

    def onDownloadComplete(self):
        with download_dict_lock:
            LOGGER.info(f"Download completed: {download_dict[self.uid].name()}")
            download = download_dict[self.uid]
            name = str(download.name()).replace('/', '')
            gid = download.gid()
            size = download.size_raw()
            if name == "None" or self.isQbit or not ospath.exists(f'{DOWNLOAD_DIR}{self.uid}/{name}'):
                name = listdir(f'{DOWNLOAD_DIR}{self.uid}')[-1]
            m_path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        if self.isZip:
            try:
                with download_dict_lock:
                    download_dict[self.uid] = ZipStatus(name, m_path, size)
                path = m_path + ".zip"
                LOGGER.info(f'Zip: orig_path: {m_path}, zip_path: {path}')
                if self.pswd is not None:
                    if self.isLeech and int(size) > MAX_LEECH_SIZE:
                        srun(["7z", f"-v{MAX_LEECH_SIZE}b", "a", "-mx=0", f"-p{self.pswd}", path, m_path])
                    else:
                        srun(["7z", "a", "-mx=0", f"-p{self.pswd}", path, m_path])
                elif self.isLeech and int(size) > MAX_LEECH_SIZE:
                    srun(["7z", f"-v{MAX_LEECH_SIZE}b", "a", "-mx=0", path, m_path])
                else:
                    srun(["7z", "a", "-mx=0", path, m_path])
            except FileNotFoundError:
                LOGGER.info('File to archive not found!')
                self.onUploadError('Internal error occurred!!')
                return
            if self.isLeech:
                try:
                    rmtree(m_path)
                except:
                    osremove(m_path)
        elif self.extract:
            try:
                if ospath.isfile(m_path):
                    path = get_base_name(m_path)
                LOGGER.info(f"Extracting: {name}")
                with download_dict_lock:
                    download_dict[self.uid] = ExtractStatus(name, m_path, size, self.message)
                if ospath.isdir(m_path):
                    for dirpath, subdir, files in walk(m_path, topdown=False):
                        for file_ in files:
                            if file_.endswith(".zip") or re_search(r'\.part0*1\.rar$|\.7z\.0*1$|\.zip\.0*1$', file_) \
                               or (file_.endswith(".rar") and not re_search(r'\.part\d+\.rar$', file_)):
                                m_path = ospath.join(dirpath, file_)
                                if self.pswd is not None:
                                    result = srun(["7z", "x", f"-p{self.pswd}", m_path, f"-o{dirpath}", "-aot"])
                                else:
                                    result = srun(["7z", "x", m_path, f"-o{dirpath}", "-aot"])
                                if result.returncode != 0:
                                    LOGGER.error('Unable to extract archive!')
                        for file_ in files:
                            if file_.endswith((".rar", ".zip")) or re_search(r'\.r\d+$|\.7z\.\d+$|\.z\d+$|\.zip\.\d+$', file_):
                                del_path = ospath.join(dirpath, file_)
                                osremove(del_path)
                    path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
                else:
                    if self.pswd is not None:
                        result = srun(["bash", "pextract", m_path, self.pswd])
                    else:
                        result = srun(["bash", "extract", m_path])
                    if result.returncode == 0:
                        LOGGER.info(f"Extracted Path: {path}")
                        osremove(m_path)
                    else:
                        LOGGER.error('Unable to extract archive! Uploading anyway')
                        path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
            except NotSupportedExtractionArchive:
                LOGGER.info("Not any valid archive, uploading file as it is.")
                path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        else:
            path = f'{DOWNLOAD_DIR}{self.uid}/{name}'
        up_name = PurePath(path).name
        up_path = f'{DOWNLOAD_DIR}{self.uid}/{up_name}'
        if self.isLeech and not self.isZip:
            checked = False
            for dirpath, subdir, files in walk(f'{DOWNLOAD_DIR}{self.uid}', topdown=False):
                for file_ in files:
                    f_path = ospath.join(dirpath, file_)
                    f_size = ospath.getsize(f_path)
                    if int(f_size) > MAX_LEECH_SIZE:
                        if not checked:
                            checked = True
                            with download_dict_lock:
                                download_dict[self.uid] = SplitStatus(up_name, up_path, size)
                            LOGGER.info(f"Splitting: {up_name}")
                        split_file(f_path, f_size, file_, dirpath, MAX_LEECH_SIZE)
                        osremove(f_path)
        if self.isLeech:
            size = get_path_size(f'{DOWNLOAD_DIR}{self.uid}')
            LOGGER.info(f"Leech Name: {up_name}")
            tg = TgUploader(up_name, self)
            tg_upload_status = TgUploadStatus(tg, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = tg_upload_status
            update_all_messages()
            tg.upload()
        else:
            size = get_path_size(up_path)
            LOGGER.info(f"Upload Name: {up_name}")
            drive = GoogleDriveHelper(up_name, self)
            upload_status = UploadStatus(drive, size, gid, self)
            with download_dict_lock:
                download_dict[self.uid] = upload_status
            update_all_messages()
            drive.upload(up_name)

    def onDownloadError(self, error):
        reply_to = self.message.reply_to_message
        if reply_to is not None:
            try:
                reply_to.delete()
            except Exception as error:
                LOGGER.warning(error)
                pass
        error = error.replace('<', ' ').replace('>', ' ')
        clean_download(f'{DOWNLOAD_DIR}{self.uid}')
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        msg = f"{self.tag} your download has been stopped due to: {error}"
        sendMessage(msg, self.bot, self.message)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.message.link)

    def onUploadComplete(self, link: str, size, files, folders, typ, name: str):
        buttons = ButtonMaker()
        # this is inspired by def mirror to get the link from message
        mesg = self.message.text.split('\n')
        message_args = mesg[0].split(' ', maxsplit=1)
        reply_to = self.message.reply_to_message
        if self.message.chat.type != 'private' and AUTO_DELETE_UPLOAD_MESSAGE_DURATION != -1:
            if reply_to is not None:
                try:
                    reply_to.delete()
                except Exception as error:
                    LOGGER.warning(error)
                    pass
        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.message.link)
        msg = f"<b>Name: </b><code>{escape(name)}</code>\n\n<b>Size: </b>{size}"
        if self.isLeech:
            if SOURCE_LINK is True:
                try:
                    source_link = message_args[1]
                    if is_magnet(source_link):
                        link = telegraph.create_page(
                        title='Helios-Mirror Source Link',
                        content=source_link,
                    )["path"]
                        buttons.buildbutton(f"🔗 Source Link", f"https://telegra.ph/{link}")
                    else:
                        buttons.buildbutton(f"🔗 Source Link", source_link)
                except Exception as e:
                    LOGGER.warning(e)
                pass
                if reply_to is not None:
                    try:
                        reply_text = reply_to.text
                        if is_url(reply_text):
                            source_link = reply_text.strip()
                            if is_magnet(source_link):
                                link = telegraph.create_page(
                                    title='Helios-Mirror Source Link',
                                    content=source_link,
                                )["path"]
                                buttons.buildbutton(f"🔗 Source Link", f"https://telegra.ph/{link}")
                            else:
                                buttons.buildbutton(f"🔗 Source Link", source_link)
                    except Exception as e:
                        LOGGER.warning(e)
                        pass
            if BOT_PM:
                bot_d = bot.get_me()
                b_uname = bot_d.username
                botstart = f"http://t.me/{b_uname}"
                buttons.buildbutton("View file in PM", f"{botstart}")
            msg += f'\n<b>Total Files: </b>{folders}'
            if typ != 0:
                msg += f'\n<b>Corrupted Files: </b>{typ}'
            msg += f'\n<b>cc: </b>{self.tag}\n\n'
            if not files:
                uploadmsg = sendMessage(msg, self.bot, self.message)
            else:
                fmsg = ''
                for index, (link, name) in enumerate(files.items(), start=1):
                    fmsg += f"{index}. <a href='{link}'>{name}</a>\n"
                    if len(fmsg.encode() + msg.encode()) > 4000:
                        uploadmsg = sendMarkup(msg + fmsg, self.bot, self.message, InlineKeyboardMarkup(buttons.build_menu(2)))
                        sleep(1)
                        fmsg = ''
                if fmsg != '':
                    uploadmsg = sendMarkup(msg + fmsg, self.bot, self.message, InlineKeyboardMarkup(buttons.build_menu(2)))
                    Thread(target=auto_delete_upload_message, args=(bot, self.message, uploadmsg)).start()
        else:
            msg += f'\n\n<b>Type: </b>{typ}'
            if ospath.isdir(f'{DOWNLOAD_DIR}{self.uid}/{name}'):
                msg += f'\n<b>SubFolders: </b>{folders}'
                msg += f'\n<b>Files: </b>{files}'
            msg += f'\n\n<b>cc: </b>{self.tag}'
            linkk = f'https://linksearn.site/st?api=8b088f1bec72e5db45502b832a1116b99e11e876&url={link}'
            linkl = get_shortlink(linkk)
            buttons = ButtonMaker()
            buttons.buildbutton("☁️ Drive Link", linkl)
            LOGGER.info(f'Done Uploading {name}')
            if INDEX_URL is not None:
                url_path = rutils.quote(f'{name}')
                share_urll = f'https://linksearn.site/st?api=8b088f1bec72e5db45502b832a1116b99e11e876&url={INDEX_URL}/{url_path}'
                share_url = get_shortlink(share_urll)
                if ospath.isdir(f'{DOWNLOAD_DIR}/{self.uid}/{name}'):
                    share_url += '/'
                    buttons.buildbutton("⚡ Index Link", share_url)
                else:
                    buttons.buildbutton("⚡ Index Link", share_url)
                    if VIEW_LINK:
                        share_urlk = f'https://linksearn.site/st?api=8b088f1bec72e5db45502b832a1116b99e11e876&url={INDEX_URL}/{url_path}?a=view'
                        share_urls = get_shortlink(share_urlk)
                        buttons.buildbutton("🌐 View Link", share_urls)
            if BUTTON_FOUR_NAME is not None and BUTTON_FOUR_URL is not None:
                buttons.buildbutton(f"{BUTTON_FOUR_NAME}", f"{BUTTON_FOUR_URL}")
            if BUTTON_FIVE_NAME is not None and BUTTON_FIVE_URL is not None:
                buttons.buildbutton(f"{BUTTON_FIVE_NAME}", f"{BUTTON_FIVE_URL}")
            if BUTTON_SIX_NAME is not None and BUTTON_SIX_URL is not None:
                buttons.buildbutton(f"{BUTTON_SIX_NAME}", f"{BUTTON_SIX_URL}")
            if SOURCE_LINK is True:
                try:
                    mesg = message_args[1]
                    if is_magnet(mesg):
                        link = telegraph.create_page(
                            title='Helios-Mirror Source Link',
                            content=mesg,
                        )["path"]
                        buttons.buildbutton(f"🔗 Source Link", f"https://telegra.ph/{link}")
                    elif is_url(mesg):
                        source_link = mesg
                        if source_link.startswith(("|", "pswd: ")):
                            pass
                        else:
                            buttons.buildbutton(f"🔗 Source Link", source_link)
                    else:
                        pass
                except Exception as e:
                    LOGGER.warning(e)
                    pass
            if reply_to is not None:
                try:
                    reply_text = reply_to.text
                    if is_url(reply_text):
                        source_link = reply_text.strip()
                        if is_magnet(source_link):
                            link = telegraph.create_page(
                                title='Helios-Mirror Source Link',
                                content=source_link,
                            )["path"]
                            buttons.buildbutton(f"🔗 Source Link", f"https://telegra.ph/{link}")
                        else:
                            buttons.buildbutton(f"🔗 Source Link", source_link)
                except Exception as e:
                    LOGGER.warning(e)
                    pass
            else:
                pass
            uploadmsg = sendMarkup(msg, self.bot, self.message, InlineKeyboardMarkup(buttons.build_menu(2)))
            Thread(target=auto_delete_upload_message, args=(bot, self.message, uploadmsg)).start()
            if MIRROR_LOGS:
                try:
                    for chatid in MIRROR_LOGS:
                        bot.sendMessage(chat_id=chatid, text=msg,
                                        reply_markup=InlineKeyboardMarkup(buttons.build_menu(2)),
                                        parse_mode=ParseMode.HTML)
                except Exception as e:
                    LOGGER.warning(e)
            if BOT_PM and self.message.chat.type != 'private':
                try:
                    bot.sendMessage(chat_id=self.user_id, text=msg,
                                    reply_markup=InlineKeyboardMarkup(buttons.build_menu(2)),
                                    parse_mode=ParseMode.HTML)
                except Exception as e:
                    LOGGER.warning(e)
                    return
        clean_download(f'{DOWNLOAD_DIR}{self.uid}')
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        if count == 0:
            self.clean()
        else:
            update_all_messages()
    def onUploadError(self, error):
        reply_to = self.message.reply_to_message
        if reply_to is not None:
            try:
                reply_to.delete()
            except Exception as error:
                LOGGER.warning(f"ewww {error}")
                pass
        e_str = error.replace('<', '').replace('>', '')
        clean_download(f'{DOWNLOAD_DIR}{self.uid}')
        with download_dict_lock:
            try:
                del download_dict[self.uid]
            except Exception as e:
                LOGGER.error(str(e))
            count = len(download_dict)
        sendMessage(f"{self.tag} {e_str}", self.bot, self.message)
        if count == 0:
            self.clean()
        else:
            update_all_messages()

        if not self.isPrivate and INCOMPLETE_TASK_NOTIFIER and DB_URI is not None:
            DbManger().rm_complete_task(self.message.link)

def _mirror(bot, message, isZip=False, extract=False, isQbit=False, isLeech=False, pswd=None, multi=0):
    buttons = ButtonMaker()
    if BOT_PM and message.chat.type != 'private':
        try:
            msg1 = f'Added your Requested link to Download\n'
            send = bot.sendMessage(message.from_user.id, text=msg1)
            send.delete()
        except Exception as e:
            LOGGER.warning(e)
            bot_d = bot.get_me()
            b_uname = bot_d.username
            uname = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.first_name}</a>'
            botstart = f"http://t.me/{b_uname}"
            buttons.buildbutton("Click Here to Start Me", f"{botstart}")
            startwarn = f"Dear {uname},\n\n<b>I found that you haven't started me in PM (Private Chat) yet.</b>\n\n" \
                        f"From now on i will give link and leeched files in PM and log channel only"
            message = sendMarkup(startwarn, bot, message, InlineKeyboardMarkup(buttons.build_menu(2)))
            Thread(target=auto_delete_message, args=(bot, message, message)).start()
            return
    if message.chat.type == 'private' and len(LEECH_LOG) == 0 and isLeech and MAX_LEECH_SIZE == 4194304000:
        text = f"Leech Log is Empty you Can't use bot in PM,\nYou Can use <i>/{BotCommands.AddleechlogCommand} chat_id </i> to add leech log."
        sendMessage(text, bot, message)
        return
    mesg = message.text.split('\n')
    message_args = mesg[0].split(' ', maxsplit=1)
    name_args = mesg[0].split('|', maxsplit=1)
    qbitsel = False
    is_gdtot = False
    try:
        link = message_args[1]
        if link.startswith("s ") or link == "s":
            qbitsel = True
            message_args = mesg[0].split(' ', maxsplit=2)
            link = message_args[2].strip()
        elif link.isdigit():
            multi = int(link)
            raise IndexError
        if link.startswith(("|", "pswd: ")):
            raise IndexError
    except:
        link = ''
    try:
        name = name_args[1]
        name = name.split(' pswd: ')[0]
        name = name.strip()
    except:
        name = ''
    link = re_split(r"pswd:| \|", link)[0]
    link = link.strip()
    pswdMsg = mesg[0].split(' pswd: ')
    if len(pswdMsg) > 1:
        pswd = pswdMsg[1]

    if message.from_user.username:
        tag = f"@{message.from_user.username}"
    else:
        tag = message.from_user.mention_html(message.from_user.first_name)

    reply_to = message.reply_to_message
    if reply_to is not None:
        file = None
        media_array = [reply_to.document, reply_to.video, reply_to.audio]
        for i in media_array:
            if i is not None:
                file = i
                break

        if not reply_to.from_user.is_bot:
            if reply_to.from_user.username:
                tag = f"@{reply_to.from_user.username}"
            else:
                tag = reply_to.from_user.mention_html(reply_to.from_user.first_name)

        if not is_url(link) and not is_magnet(link) or len(link) == 0:
            if file is None:
                reply_text = reply_to.text
                if is_url(reply_text) or is_magnet(reply_text):
                    link = reply_text.strip()
            elif file.mime_type != "application/x-bittorrent" and not isQbit:
                listener = MirrorListener(bot, message, isZip, extract, isQbit, isLeech, pswd, tag)
                Thread(target=TelegramDownloadHelper(listener).add_download, args=(message, f'{DOWNLOAD_DIR}{listener.uid}/', name)).start()
                if multi > 1:
                    sleep(4)
                    nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
                    nextmsg = sendMessage(message_args[0], bot, nextmsg)
                    nextmsg.from_user.id = message.from_user.id
                    multi -= 1
                    sleep(4)
                    Thread(target=_mirror, args=(bot, nextmsg, isZip, extract, isQbit, isLeech, pswd, multi)).start()
                return
            else:
                link = file.get_file().file_path

    if not is_url(link) and not is_magnet(link) and not ospath.exists(link):
        help_msg = "<b>Send link along with command line:</b>"
        help_msg += "\n<code>/command</code> {link} |newname pswd: xx [zip/unzip]"
        help_msg += "\n\n<b>By replying to link or file:</b>"
        help_msg += "\n<code>/command</code> |newname pswd: xx [zip/unzip]"
        help_msg += "\n\n<b>Direct link authorization:</b>"
        help_msg += "\n<code>/command</code> {link} |newname pswd: xx\nusername\npassword"
        help_msg += "\n\n<b>Qbittorrent selection:</b>"
        help_msg += "\n<code>/qbcommand</code> <b>s</b> {link} or by replying to {file/link}"
        help_msg += "\n\n<b>Multi links only by replying to first link or file:</b>"
        help_msg += "\n<code>/command</code> 10(number of links/files)"
        return sendMessage(help_msg, bot, message)

    LOGGER.info(link)

    if not is_mega_link(link) and not isQbit and not is_magnet(link) \
        and not is_gdrive_link(link) and not link.endswith('.torrent'):
        content_type = get_content_type(link)
        if content_type is None or re_match(r'text/html|text/plain', content_type):
            try:
                is_gdtot = is_gdtot_link(link)
                link = direct_link_generator(link)
                LOGGER.info(f"Generated link: {link}")
            except DirectDownloadLinkException as e:
                LOGGER.info(str(e))
                if str(e).startswith('ERROR:'):
                    return sendMessage(str(e), bot, message)
    elif isQbit and not is_magnet(link) and not ospath.exists(link):
        if link.endswith('.torrent') or "https://api.telegram.org/file/" in link:
            content_type = None
        else:
            content_type = get_content_type(link)
        if content_type is None or re_match(r'application/x-bittorrent|application/octet-stream', content_type):
            try:
                resp = rget(link, timeout=10, headers = {'user-agent': 'Wget/1.12'})
                if resp.status_code == 200:
                    file_name = str(time()).replace(".", "") + ".torrent"
                    with open(file_name, "wb") as t:
                        t.write(resp.content)
                    link = str(file_name)
                else:
                    return sendMessage(f"{tag} ERROR: link got HTTP response: {resp.status_code}", bot, message)
            except Exception as e:
                error = str(e).replace('<', ' ').replace('>', ' ')
                if error.startswith('No connection adapters were found for'):
                    link = error.split("'")[1]
                else:
                    LOGGER.error(str(e))
                    return sendMessage(tag + " " + error, bot, message)
        else:
            msg = "Qb commands for torrents only. if you are trying to dowload torrent then report."
            return sendMessage(msg, bot, message)


    listener = MirrorListener(bot, message, isZip, extract, isQbit, isLeech, pswd, tag)

    if is_gdrive_link(link):
        if not isZip and not extract and not isLeech:
            gmsg = f"Use /{BotCommands.CloneCommand} to clone Google Drive file/folder\n\n"
            gmsg += f"Use /{BotCommands.ZipMirrorCommand} to make zip of Google Drive folder\n\n"
            gmsg += f"Use /{BotCommands.UnzipMirrorCommand} to extracts Google Drive archive file"
            sendMessage(gmsg, bot, message)
        else:
            Thread(target=add_gd_download, args=(link, listener, is_gdtot)).start()
    elif is_mega_link(link):
        if MEGA_API_KEY is not None:
            Thread(target=MegaDownloader(listener).add_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}/')).start()
        else:
            sendMessage('MEGA_API_KEY not Provided!', bot, message)
    elif isQbit and (is_magnet(link) or ospath.exists(link)):
        Thread(target=QbDownloader(listener).add_qb_torrent, args=(link, f'{DOWNLOAD_DIR}{listener.uid}', qbitsel)).start()
    else:
        if len(mesg) > 1:
            try:
                ussr = mesg[1]
            except:
                ussr = ''
            try:
                pssw = mesg[2]
            except:
                pssw = ''
            auth = f"{ussr}:{pssw}"
            auth = "Basic " + b64encode(auth.encode()).decode('ascii')
        else:
            auth = ''
        Thread(target=add_aria2c_download, args=(link, f'{DOWNLOAD_DIR}{listener.uid}', listener, name, auth)).start()

    if multi > 1:
        sleep(4)
        nextmsg = type('nextmsg', (object, ), {'chat_id': message.chat_id, 'message_id': message.reply_to_message.message_id + 1})
        msg = message_args[0]
        if len(mesg) > 2:
            msg += '\n' + mesg[1] + '\n' + mesg[2]
        nextmsg = sendMessage(msg, bot, nextmsg)
        nextmsg.from_user.id = message.from_user.id
        multi -= 1
        sleep(4)
        Thread(target=_mirror, args=(bot, nextmsg, isZip, extract, isQbit, isLeech, pswd, multi)).start()


def mirror(update, context):
    _mirror(context.bot, update.message)

def unzip_mirror(update, context):
    _mirror(context.bot, update.message, extract=True)

def zip_mirror(update, context):
    _mirror(context.bot, update.message, True)

def qb_mirror(update, context):
    _mirror(context.bot, update.message, isQbit=True)

def qb_unzip_mirror(update, context):
    _mirror(context.bot, update.message, extract=True, isQbit=True)

def qb_zip_mirror(update, context):
    _mirror(context.bot, update.message, True, isQbit=True)

def leech(update, context):
    _mirror(context.bot, update.message, isLeech=True)

def unzip_leech(update, context):
    _mirror(context.bot, update.message, extract=True, isLeech=True)

def zip_leech(update, context):
    _mirror(context.bot, update.message, True, isLeech=True)

def qb_leech(update, context):
    _mirror(context.bot, update.message, isQbit=True, isLeech=True)

def qb_unzip_leech(update, context):
    _mirror(context.bot, update.message, extract=True, isQbit=True, isLeech=True)

def qb_zip_leech(update, context):
    _mirror(context.bot, update.message, True, isQbit=True, isLeech=True)

mirror_handler = CommandHandler(BotCommands.MirrorCommand, mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_mirror_handler = CommandHandler(BotCommands.UnzipMirrorCommand, unzip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_mirror_handler = CommandHandler(BotCommands.ZipMirrorCommand, zip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_mirror_handler = CommandHandler(BotCommands.QbMirrorCommand, qb_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_mirror_handler = CommandHandler(BotCommands.QbUnzipMirrorCommand, qb_unzip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_mirror_handler = CommandHandler(BotCommands.QbZipMirrorCommand, qb_zip_mirror,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
leech_handler = CommandHandler(BotCommands.LeechCommand, leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
unzip_leech_handler = CommandHandler(BotCommands.UnzipLeechCommand, unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
zip_leech_handler = CommandHandler(BotCommands.ZipLeechCommand, zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_leech_handler = CommandHandler(BotCommands.QbLeechCommand, qb_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_unzip_leech_handler = CommandHandler(BotCommands.QbUnzipLeechCommand, qb_unzip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)
qb_zip_leech_handler = CommandHandler(BotCommands.QbZipLeechCommand, qb_zip_leech,
                                filters=CustomFilters.authorized_chat | CustomFilters.authorized_user, run_async=True)

dispatcher.add_handler(mirror_handler)
dispatcher.add_handler(unzip_mirror_handler)
dispatcher.add_handler(zip_mirror_handler)
dispatcher.add_handler(qb_mirror_handler)
dispatcher.add_handler(qb_unzip_mirror_handler)
dispatcher.add_handler(qb_zip_mirror_handler)
dispatcher.add_handler(leech_handler)
dispatcher.add_handler(unzip_leech_handler)
dispatcher.add_handler(zip_leech_handler)
dispatcher.add_handler(qb_leech_handler)
dispatcher.add_handler(qb_unzip_leech_handler)
dispatcher.add_handler(qb_zip_leech_handler)
