import os
import sys

# Обеспечиваем корректный вывод UTF-8 в консоль
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# Регистрация шрифтов с поддержкой кириллицы
FONT_DIR = "C:/Windows/Fonts"
pdfmetrics.registerFont(TTFont('Arial', os.path.join(FONT_DIR, 'arial.ttf')))
pdfmetrics.registerFont(TTFont('Arial-Bold', os.path.join(FONT_DIR, 'arialbd.ttf')))
pdfmetrics.registerFont(TTFont('Arial-Italic', os.path.join(FONT_DIR, 'ariali.ttf')))
pdfmetrics.registerFont(TTFont('Consolas', os.path.join(FONT_DIR, 'consola.ttf')))
pdfmetrics.registerFont(TTFont('Consolas-Bold', os.path.join(FONT_DIR, 'consolab.ttf')))


class NumberedCanvas(canvas.Canvas):
    """Двухпроходный холст для нумерации страниц 'Страница X из Y' и колонтитулов."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Arial", 8)
        self.setFillColor(colors.HexColor("#718096"))

        # Верхний колонтитул (кроме титульной страницы)
        if self._pageNumber > 1:
            self.drawString(18 * mm, 287 * mm, "Регламент передачи проекта заказчику — Trecker Bot (MVP)")
            self.setStrokeColor(colors.HexColor("#CBD5E0"))
            self.setLineWidth(0.5)
            self.line(18 * mm, 284 * mm, 192 * mm, 284 * mm)

        # Нижний колонтитул
        page_str = f"Страница {self._pageNumber} из {page_count}"
        self.drawRightString(192 * mm, 10 * mm, page_str)
        self.drawString(18 * mm, 10 * mm, "Конфиденциально • Передача Telegram-бота заказчику «под ключ»")
        self.setStrokeColor(colors.HexColor("#CBD5E0"))
        self.setLineWidth(0.5)
        self.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
        self.restoreState()


def build_pdf(filename="Инструкция_по_передаче_бота_заказчику.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'DocTitle',
        fontName='Arial-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#1A365D'),
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        fontName='Arial',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor('#4A5568'),
        spaceAfter=8
    )

    h1_style = ParagraphStyle(
        'Heading1_Custom',
        fontName='Arial-Bold',
        fontSize=11.5,
        leading=15,
        textColor=colors.HexColor('#1A365D'),
        spaceBefore=7,
        spaceAfter=4,
        keepWithNext=True
    )

    h2_style = ParagraphStyle(
        'Heading2_Custom',
        fontName='Arial-Bold',
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor('#2B6CB0'),
        spaceBefore=5,
        spaceAfter=3,
        keepWithNext=True
    )

    body_style = ParagraphStyle(
        'Body_Custom',
        fontName='Arial',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#2D3748'),
        spaceAfter=3
    )

    bullet_style = ParagraphStyle(
        'Bullet_Custom',
        fontName='Arial',
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor('#2D3748'),
        leftIndent=10,
        spaceAfter=2
    )

    code_style = ParagraphStyle(
        'CodeBlock',
        fontName='Consolas',
        fontSize=7.2,
        leading=9.5,
        textColor=colors.HexColor('#1A202C')
    )

    alert_style = ParagraphStyle(
        'AlertText',
        fontName='Arial',
        fontSize=8,
        leading=11,
        textColor=colors.HexColor('#744210')
    )

    def code_box(code_text):
        escaped = code_text.strip().replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br/>')
        p = Paragraph(escaped, code_style)
        t = Table([[p]], colWidths=[174 * mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F7FAFC')),
            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#CBD5E0')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        return t

    def alert_box(text):
        p = Paragraph(f"<b>ВАЖНО:</b> {text}", alert_style)
        t = Table([[p]], colWidths=[174 * mm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEFCBF')),
            ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#D69E2E')),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        return t

    story = []

    # ================= PAGE 1 =================
    story.append(Paragraph("Инструкция по передаче бота заказчику", title_style))
    story.append(Paragraph(
        "Персональный AI-ассистент и трекер задач для Telegram (MVP по ТЗ клиента)<br/>"
        "<b>Стек:</b> Python 3.12, PTB, Ollama (Llama 3.1 8B), Whisper, Google Sheets / Local JSON",
        subtitle_style
    ))
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor('#2B6CB0'), spaceBefore=0, spaceAfter=6))

    intro_table = Table([[
        Paragraph(
            "<b>Назначение регламента:</b> пошаговое руководство для развёртывания и передачи Telegram-бота заказчику «под ключ». "
            "Охватывает аренду и настройку VPS, перенос прав владения, конфигурацию хранилища, "
            "автозапуск сервиса, регламент приёмочного тестирования и чек-лист передаваемых доступов.",
            body_style
        )
    ]], colWidths=[174 * mm])
    intro_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EBF8FF')),
        ('BOX', (0, 0), (-1, -1), 0.6, colors.HexColor('#bee3f8')),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]))
    story.append(intro_table)
    story.append(Spacer(1, 4))

    story.append(Paragraph("Этап 1. Подготовка сервера заказчика (VPS)", h1_style))
    story.append(Paragraph(
        "Бот использует локальные нейросети (Llama 3.1 8B для SMART-структурирования задач и Whisper для транскрипции речи). "
        "Для круглосуточной и быстрой работы требуется выделенный виртуальный сервер (VPS).",
        body_style
    ))

    vps_table_data = [
        [Paragraph("<b>Параметр</b>", body_style), Paragraph("<b>Минимум</b>", body_style), Paragraph("<b>Рекомендовано</b>", body_style)],
        [Paragraph("ОС", body_style), Paragraph("Ubuntu 22.04 LTS (x86_64)", body_style), Paragraph("Ubuntu 22.04 / 24.04 LTS", body_style)],
        [Paragraph("CPU", body_style), Paragraph("2 vCPU", body_style), Paragraph("4 vCPU", body_style)],
        [Paragraph("RAM", body_style), Paragraph("4 ГБ (+ 4 ГБ Swap)", body_style), Paragraph("8 ГБ RAM (+ 4 ГБ Swap)", body_style)],
        [Paragraph("Диск (NVMe/SSD)", body_style), Paragraph("30 ГБ", body_style), Paragraph("40-50 ГБ NVMe", body_style)],
        [Paragraph("Провайдеры в РФ", body_style), Paragraph("Timeweb Cloud, Selectel, Beget", body_style), Paragraph("Стоимость: ~900-1400 ₽/мес.", body_style)],
    ]
    t_vps = Table(vps_table_data, colWidths=[44 * mm, 65 * mm, 65 * mm])
    t_vps.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EDF2F7')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('TOPPADDING', (0, 0), (-1, -1), 2.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t_vps)
    story.append(Spacer(1, 4))

    story.append(Paragraph("1.1. Базовая настройка сервера по SSH (установка пакетов и Swap-файла):", h2_style))
    story.append(code_box(
"""sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip ffmpeg git curl

# Создание обязательного Swap-файла подкачки 4 ГБ (защита от Out-Of-Memory при работе LLM):
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab"""
    ))
    story.append(Spacer(1, 4))

    story.append(Paragraph("1.2. Установка Ollama и скачивание модели Llama 3.1 8B:", h2_style))
    story.append(code_box(
"""curl -fsSL https://ollama.ai/install.sh | sh
ollama pull llama3.1:8b
# Проверка доступности:
curl http://localhost:11434/api/tags"""
    ))

    # Переход на страницу 2
    story.append(PageBreak())

    # ================= PAGE 2 =================
    story.append(Paragraph("Этап 2. Передача прав на Telegram-бота", h1_style))
    story.append(Paragraph("Передачу можно осуществить одним из двух вариантов:", body_style))
    story.append(Paragraph("• <b>Вариант А (Передача прав на текущего бота через @BotFather):</b>", bullet_style))
    story.append(Paragraph("  1. Открыть <code>@BotFather</code> с аккаунта текущего владельца бота.", bullet_style))
    story.append(Paragraph("  2. Выполнить команду <code>/mybots</code> → выбрать бота проекта.", bullet_style))
    story.append(Paragraph("  3. Выбрать <b>Bot Settings</b> → <b>Transfer Ownership</b>.", bullet_style))
    story.append(Paragraph("  4. Ввести username заказчика в Telegram и подтвердить передачу через 2FA-пароль.", bullet_style))
    story.append(Paragraph("• <b>Вариант Б (Заказчик создаёт нового бота):</b> заказчик пишет <code>/newbot</code> в <code>@BotFather</code>, задаёт имя и передаёт полученный токен разработчику.", bullet_style))
    story.append(Paragraph("• <b>Определение Telegram ID заказчика:</b> заказчик узнаёт свой цифровой ID через <code>@userinfobot</code> или команду <code>/myid</code> (прописывается в <code>ADMIN_IDS</code>).", bullet_style))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Этап 3. Настройка хранилища данных", h1_style))
    story.append(Paragraph("Бот поддерживает два варианта бэкенда (параметр <code>STORAGE_BACKEND</code>):", body_style))
    story.append(Paragraph("1. <b>Google Sheets (наглядно для заказчика):</b>", h2_style))
    story.append(Paragraph("• Создать Google Таблицу на аккаунте заказчика (или передать права владельца на текущую).", bullet_style))
    story.append(Paragraph("• В Google Cloud Console создать Service Account, активировать Google Sheets API и Google Drive API.", bullet_style))
    story.append(Paragraph("• Скачать JSON-ключ в <code>secrets/service_account.json</code> и выдать email сервисного аккаунта доступ «Редактор» к таблице.", bullet_style))
    story.append(Paragraph("2. <b>Локальный JSON (автономно без внешних сервисов):</b>", h2_style))
    story.append(Paragraph("При значении <code>STORAGE_BACKEND=local</code> данные сохраняются локально в <code>data/tasks.json</code> и <code>data/employees.json</code>.", bullet_style))
    story.append(Spacer(1, 4))

    story.append(Paragraph("Этап 4. Развёртывание проекта на сервере заказчика", h1_style))
    story.append(Paragraph("4.1. Подготовка директории и установка зависимостей Python:", h2_style))
    story.append(code_box(
"""sudo mkdir -p /opt/taskbot && sudo chown -R $USER:$USER /opt/taskbot
# Скопировать файлы проекта в /opt/taskbot, затем перейти в каталог:
cd /opt/taskbot

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-ai.txt"""
    ))
    story.append(Spacer(1, 4))

    story.append(Paragraph("4.2. Настройка конфигурационного файла secrets/.env:", h2_style))
    story.append(code_box(
"""mkdir -p secrets
cat << 'EOF' > secrets/.env
TG_BOT_TOKEN=ваш_токен_от_BotFather
ADMIN_IDS=telegram_id_заказчика
CUSTOMER_IDS=telegram_id_заказчика
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
WHISPER_MODEL=base
STORAGE_BACKEND=local

# Для Google Таблицы:
# STORAGE_BACKEND=sheets
# GOOGLE_SERVICE_ACCOUNT=secrets/service_account.json
# GOOGLE_SHEET_ID=id_таблицы_из_адресной_строки
EOF"""
    ))
    story.append(Spacer(1, 4))

    story.append(Paragraph("4.3. Автоматический тест готовности системы:", h2_style))
    story.append(code_box("python main.py --check"))
    story.append(Paragraph("Все 5 модулей (Config, Storage, Ollama, Whisper, Bot) должны вернуть статус <code>[OK]</code>.", body_style))

    # Переход на страницу 3
    story.append(PageBreak())

    # ================= PAGE 3 =================
    story.append(Paragraph("Этап 5. Настройка автозапуска (Systemd-сервис)", h1_style))
    story.append(Paragraph("Служба systemd гарантирует автоматический старт при перезагрузке и перезапуск бота при сбоях:", body_style))
    story.append(code_box(
"""sudo tee /etc/systemd/system/taskbot.service > /dev/null << 'EOF'
[Unit]
Description=Telegram Task Tracker AI Bot
After=network.target ollama.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/taskbot
ExecStart=/opt/taskbot/.venv/bin/python main.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload && sudo systemctl enable taskbot && sudo systemctl start taskbot"""
    ))
    story.append(Spacer(1, 3))
    story.append(Paragraph("Команды управления: <code>sudo systemctl status taskbot</code> (статус), <code>sudo systemctl restart taskbot</code> (перезапуск), <code>journalctl -u taskbot -f</code> (логи).", body_style))
    story.append(Spacer(1, 5))

    story.append(Paragraph("Этап 6. Приёмка и совместное тестирование", h1_style))
    story.append(Paragraph("План совместного приёмочного тестирования функционала с заказчиком:", body_style))

    checklist_data = [
        [Paragraph("<b>№</b>", body_style), Paragraph("<b>Действие / Проверка</b>", body_style), Paragraph("<b>Ожидаемый результат</b>", body_style)],
        [
            Paragraph("1", body_style),
            Paragraph("Команда <code>/start</code> от заказчика", body_style),
            Paragraph("Приветствие и подтверждение прав «Заказчик / Администратор»", body_style)
        ],
        [
            Paragraph("2", body_style),
            Paragraph("Добавление сотрудника:<br/><code>/add_employee @username Имя Должность</code>", body_style),
            Paragraph("Сотрудник сохранён и отображается в списке <code>/employees</code>", body_style)
        ],
        [
            Paragraph("3", body_style),
            Paragraph("Голосовая постановка задачи (с шумом и датой)", body_style),
            Paragraph("Whisper расшифровывает, Llama очищает шумы и строит SMART-карточку", body_style)
        ],
        [
            Paragraph("4", body_style),
            Paragraph("Распознавание времени и дедлайна по МСК", body_style),
            Paragraph("«в 6» → 18:00, «завтра утром» → 08:00, «через 5 минут» в таймзоне UTC+3", body_style)
        ],
        [
            Paragraph("5", body_style),
            Paragraph("Жизненный цикл задачи исполнителем", body_style),
            Paragraph("Уведомление исполнителю → кнопка «В работе» → кнопка «Готово»", body_style)
        ],
        [
            Paragraph("6", body_style),
            Paragraph("Проверка журнала действий <code>/log</code>", body_style),
            Paragraph("Логирование создания, смены статусов, напоминаний и дедлайна", body_style)
        ],
    ]
    t_check = Table(checklist_data, colWidths=[8 * mm, 83 * mm, 83 * mm])
    t_check.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EDF2F7')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E0')),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(t_check)
    story.append(Spacer(1, 5))

    story.append(Paragraph("Чек-лист передаваемых материалов и доступов", h1_style))
    story.append(Paragraph("1. <b>Доступ к VPS-серверу:</b> IP-адрес, SSH-порт, логин/пароль или SSH-ключ, доступ в панель хостинга.", bullet_style))
    story.append(Paragraph("2. <b>Владение ботом в Telegram:</b> подтверждение статуса владельца в <code>@BotFather</code>.", bullet_style))
    story.append(Paragraph("3. <b>Доступ к Google Таблице:</b> права владельца на таблицу с задачами и журнал.", bullet_style))
    story.append(Paragraph("4. <b>Памятка администратора:</b> команды (<code>/tasks</code>, <code>/employees</code>, <code>/add_employee</code>, <code>/log</code>, <code>/myid</code>).", bullet_style))
    story.append(Paragraph("5. <b>Регламент обслуживания:</b> контроль свободного места на диске и баланса VPS-хостинга.", bullet_style))
    story.append(Spacer(1, 4))

    story.append(alert_box(
        "Храните файл secrets/.env и ключи доступа в безопасности. Никогда не пересылайте токены через открытые чаты."
    ))

    # Сборка документа
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"[OK] PDF successfully generated: {filename}")


if __name__ == '__main__':
    out_name = "Инструкция_по_передаче_бота_заказчику.pdf"
    if len(sys.argv) > 1:
        out_name = sys.argv[1]
    build_pdf(out_name)
