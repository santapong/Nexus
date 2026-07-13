/**
 * Browser Web Speech API typings + helpers — the `browser` voice backend
 * of ADR-088. STT uses SpeechRecognition (webkit-prefixed in Chromium);
 * TTS uses window.speechSynthesis. Both are feature-detected so the UI
 * degrades gracefully where unsupported.
 */

export interface SpeechRecognitionResultLike {
  isFinal: boolean
  0: { transcript: string }
}

export interface SpeechRecognitionEventLike {
  resultIndex: number
  results: ArrayLike<SpeechRecognitionResultLike>
}

export interface SpeechRecognitionLike {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((event: SpeechRecognitionEventLike) => void) | null
  onend: (() => void) | null
  onerror: ((event: { error?: string }) => void) | null
  start: () => void
  stop: () => void
  abort: () => void
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike

interface WindowWithSpeech {
  SpeechRecognition?: SpeechRecognitionConstructor
  webkitSpeechRecognition?: SpeechRecognitionConstructor
}

export function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  const w = window as unknown as WindowWithSpeech
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

export function speechRecognitionSupported(): boolean {
  return getSpeechRecognition() !== null
}

export function speechSynthesisSupported(): boolean {
  return typeof window !== 'undefined' && 'speechSynthesis' in window
}

/** Speak text aloud, cancelling anything already queued. */
export function speak(text: string): void {
  if (!speechSynthesisSupported() || !text.trim()) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.rate = 1.0
  window.speechSynthesis.speak(utterance)
}

export function stopSpeaking(): void {
  if (speechSynthesisSupported()) window.speechSynthesis.cancel()
}
