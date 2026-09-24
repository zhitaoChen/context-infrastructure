# Local Whisper transcription

Copilot CLI's built-in `/voice` command only exposes its fixed streaming voice models.
It does not accept arbitrary Foundry Local speech models. Use this repository's wrapper
when you specifically want OpenAI Whisper.

## Setup

```powershell
winget install Microsoft.FoundryLocal
foundry server start
foundry model download whisper-small
```

`whisper-small` is the default because it balances CPU latency, download size, and
multilingual accuracy. You can also select `whisper-tiny`, `whisper-base`,
`whisper-medium`, or `whisper-large-v3-turbo`.

## Microphone dictation

```powershell
.\tools\voice\transcribe.ps1
```

Foundry opens an interactive microphone transcription session. Press `Ctrl+C` to stop.

## Transcribe an audio file

```powershell
.\tools\voice\transcribe.ps1 -File .\recording.wav -Language zh
```

Save plain text or JSON:

```powershell
.\tools\voice\transcribe.ps1 -File .\recording.wav -OutputPath .\transcript.txt
.\tools\voice\transcribe.ps1 -File .\recording.wav -Json -OutputPath .\transcript.json
```

Use a larger model when accuracy matters more than latency:

```powershell
.\tools\voice\transcribe.ps1 -File .\recording.wav -Model whisper-large-v3-turbo
```
