Loyiha tuzilmasi
```
mini-jarvis/
├── main.py              ← FastAPI backend
├── requirements.txt
├── run.bat / run.sh
├── models/              ← yuklangan Vosk modellari
├── output/              ← TTS chiqish WAV fayllar
├── uploads/             ← vaqtinchalik yuklangan fayllar
├── static/css/style.css ← animatsiyali dizayn
└── templates/
    ├── home.html        ← asosiy sahifa
    ├── stt.html         ← mikrofon + fayl yuklash
    └── tts.html         ← matn → ovoz
```

## Ishga tushirish

 `cd e:/GitHub/mini-jarvis`
 `pip install -r requirements.txt`
 `python main.py`
 ` → http://localhost:8000`

## Imkoniyatlar
```
STT	TTS
🇺🇸 English	✓	✓ (1 speaker)
🇷🇺 Russian	✓	✓ 5 speaker (Aidar, Baya, Kseniya, Xenia, Eugene)
🇩🇪 German	✓	✓ (1 speaker)
🇫🇷 French	✓	—
🇪🇸 Spanish	✓	—
🇺🇿 Uzbek	✓	—
🇹🇷 Turkish	✓	—
🇨🇳 Chinese	✓	—
```

## STT sahifasi:

Til tanlash → model yo'q bo'lsa avtomatik yuklab oladi (progress bar bilan)
Mikrofon: real-vaqt WebSocket transkriptsiya (ovoz yozilayotganda matn chiqadi)
Fayl yuklash: WAV/MP3/OGG yuklash, ffmpeg o'rnatilgan bo'lsa avtomatik konvertatsiya

## TTS sahifasi:

Til va speaker tanlash
Matn yozish → "Synthesize" → HTML5 audio player'da ijro etadi
So'nggi 10 ta synthesized matn tarixi
WAV fayl yuklab olish
UI: Animatsiyali gradient blob fon, floating cards, pulsing yozuv tugmasi, waveform animation, toast bildirishmalar.