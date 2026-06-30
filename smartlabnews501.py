import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import re
import time
from datetime import datetime

# ===== НАСТРОЙКИ =====
EMAIL_SENDER = "your mail"
EMAIL_PASSWORD = "enter your password"
EMAIL_RECEIVER = "your mail"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
MAX_POSTS = 50
BLOG_URL = "https://smart-lab.ru/allblog/"

# ===== ПОЛУЧЕНИЕ ССЫЛОК НА ПОСТЫ =====
def get_post_links():
    try:
        r = requests.get(BLOG_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Ошибка загрузки {BLOG_URL}: {e}")
        return []

    soup = BeautifulSoup(r.text, 'html.parser')
    links = []

    for a in soup.find_all('a', href=True):
        href = a['href']
        if re.search(r'/blog/\d+\.php', href) or re.search(r'/mobile/topic/\d+', href):
            full_url = href if href.startswith('http') else 'https://smart-lab.ru' + href
            if full_url not in links:
                links.append(full_url)
            if len(links) >= MAX_POSTS:
                break

    if len(links) < 5:
        for a in soup.select('a[href*="/blog/"]'):
            href = a['href']
            if re.search(r'/blog/\d+\.php', href):
                full_url = href if href.startswith('http') else 'https://smart-lab.ru' + href
                if full_url not in links:
                    links.append(full_url)
                if len(links) >= MAX_POSTS:
                    break

    print(f"✅ Найдено {len(links)} ссылок на посты")
    return links[:MAX_POSTS]

# ===== ИЗВЛЕЧЕНИЕ ЧИСТОГО ТЕКСТА ПОСТА (АДАПТИРОВАННАЯ ВЕРСИЯ) =====
def get_clean_post_text(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
    except Exception as e:
        print(f"❌ Ошибка загрузки {url}: {e}")
        return None

    soup = BeautifulSoup(r.text, 'html.parser')

    # 1. Удаляем мусор (скрипты, стили, навигацию)
    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'form', 'ins', 'iframe']):
        tag.decompose()

    # 2. Ищем контейнер с текстом поста
    # Сначала ищем div с классом "topic", внутри него div с классом "content"
    topic = soup.find('div', class_='topic')
    content = None
    if topic:
        content = topic.find('div', class_='content')
    # Если не нашли, пробуем другие варианты
    if not content:
        for cls in ['post-content', 'blog-post', 'article-content', 'entry-content', 'message', 'text', 'post-body']:
            content = soup.find('div', class_=re.compile(cls, re.I))
            if content:
                break
    # Если и так нет, берём весь body, но удаляем лишнее
    if not content:
        content = soup.find('body')
        if content:
            for aside in content.find_all(['aside', 'div'], class_=re.compile(r'(sidebar|menu|footer|header|ad|banner)')):
                aside.decompose()

    if not content:
        return None

    # 3. Извлекаем заголовок
    title = "Без заголовка"
    title_tag = soup.find('h1', class_='title')
    if title_tag:
        title = title_tag.get_text(strip=True)
    else:
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text(strip=True)

    # 4. Извлекаем автора и дату
    author = "Неизвестен"
    date = "Неизвестно"

    # Автор — ссылка с классом 'trader_other' или 'author'
    author_tag = soup.find('a', class_='trader_other')
    if not author_tag:
        author_tag = soup.find('a', class_=re.compile(r'author|user|nickname'))
    if author_tag:
        author = author_tag.get_text(strip=True)

    # Дата — элемент li с классом 'date'
    date_tag = soup.find('li', class_='date')
    if date_tag:
        date = date_tag.get_text(strip=True)
    else:
        date_tag = soup.find('time') or soup.find('span', class_=re.compile(r'date|time|published'))
        if date_tag:
            date = date_tag.get_text(strip=True)

    # 5. Получаем чистый текст тела (без мусора)
    raw_text = content.get_text(separator='\n', strip=True)

    # 6. Чистим текст от мусорных строк
    lines = raw_text.split('\n')
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Пропускаем строки-мусор
        if re.match(r'^\s*(\d+|Комментариев|Читать дальше|хорошо|обсудить на форуме|подписаться|Подписаться|Рейтинг|Поделиться|Нравится|В избранное|Написать комментарий|Ответить|Цитировать).*$', line, re.I):
            continue
        if re.match(r'^\s*[\d\.\-\:]+\s*$', line):
            continue
        if re.match(r'^[\#\@]\w+', line):
            continue
        if len(line) < 3:
            continue
        clean_lines.append(line)

    clean_text = '\n'.join(clean_lines)

    # Если после чистки текст слишком короткий, пробуем альтернативный подход
    if len(clean_text) < 50:
        alt_text = content.get_text(separator=' ', strip=True)
        if len(alt_text) > len(clean_text):
            clean_text = alt_text

    # 7. Убираем множественные переносы и пробелы
    clean_text = re.sub(r'\n\s*\n', '\n\n', clean_text)
    clean_text = re.sub(r' {2,}', ' ', clean_text)

    # Формируем результат
    result = f"🔗 {url}\n📌 {title}\n✍️ Автор: {author} | 📅 {date}\n\n{clean_text}"
    return result

# ===== СОХРАНЕНИЕ В ФАЙЛ =====
def save_to_file(posts_data):
    date_str = datetime.now().strftime('%Y%m%d')
    filename = f"smartlab_clean_{date_str}_50posts.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"=== SMART-LAB ПАРСИНГ (ЧИСТЫЙ ТЕКСТ) ===\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Всего постов: {len(posts_data)}\n")
        f.write("=" * 60 + "\n\n")
        for i, post_text in enumerate(posts_data, 1):
            f.write(f"\n{'='*60}\n")
            f.write(f"ПОСТ {i}\n")
            f.write(f"{'='*60}\n")
            f.write(post_text)
            f.write("\n\n")
    print(f"✅ Сохранено {len(posts_data)} постов в файл: {filename}")

    with open(filename, 'r', encoding='utf-8') as f:
        content = f.read()
    approx_tokens = len(content) // 4
    print(f"📊 Примерный объём: {len(content)} символов, ~{approx_tokens} токенов")
    return filename

# ===== ОТПРАВКА НА ПОЧТУ =====
def send_file(filename):
    msg = MIMEMultipart()
    msg["Subject"] = f"📊 Smart-Lab (чистый) — {MAX_POSTS} постов {datetime.now().strftime('%d.%m.%Y')}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    body = f"Чистые тексты {MAX_POSTS} постов со Smart-lab.\nДата: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    msg.attach(MIMEText(body, "plain"))

    try:
        with open(filename, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename={filename}')
            msg.attach(part)
    except Exception as e:
        print(f"❌ Ошибка прикрепления: {e}")
        return

    try:
        with smtplib.SMTP_SSL("smtp.yandex.ru", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        print("✅ Письмо отправлено.")
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

# ===== КОПИРОВАНИЕ В БУФЕР ОБМЕНА =====
def copy_to_clipboard(filename):
    try:
        import pyperclip
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        pyperclip.copy(content)
        print("📋 Текст скопирован в буфер обмена. Вставьте в диалог (Ctrl+V).")
    except ImportError:
        print("⚠️ pyperclip не установлен. Установите: pip install pyperclip")
    except Exception as e:
        print(f"⚠️ Ошибка копирования: {e}")

# ===== ЗАПУСК =====
if __name__ == "__main__":
    print(f"🔄 Получение ссылок на посты с {BLOG_URL}...")
    links = get_post_links()
    if not links:
        print("❌ Ссылки не найдены.")
    else:
        print(f"✅ Найдено {len(links)} ссылок.")
        posts = []
        for i, link in enumerate(links[:MAX_POSTS], 1):
            print(f"📄 Парсинг поста {i}/{MAX_POSTS}...")
            clean_text = get_clean_post_text(link)
            if clean_text:
                posts.append(clean_text)
            time.sleep(0.5)

        if posts:
            filename = save_to_file(posts)
            send_file(filename)
            copy_to_clipboard(filename)
            print("✅ Готово! Файл отправлен на почту и скопирован в буфер.")
        else:
            print("❌ Не удалось загрузить ни одного поста.")