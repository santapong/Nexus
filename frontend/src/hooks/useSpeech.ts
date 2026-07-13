import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getSpeechRecognition,
  speak,
  speechRecognitionSupported,
  speechSynthesisSupported,
  stopSpeaking,
  type SpeechRecognitionLike,
} from '@/lib/speech'

/**
 * Microphone dictation via the browser SpeechRecognition API.
 * Interim results stream through onTranscript so the composer fills live.
 */
export function useSpeechRecognition(onTranscript: (text: string, isFinal: boolean) => void) {
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null)
  const supported = speechRecognitionSupported()

  const stop = useCallback(() => {
    recognitionRef.current?.stop()
    recognitionRef.current = null
    setListening(false)
  }, [])

  const start = useCallback(() => {
    const Ctor = getSpeechRecognition()
    if (!Ctor || recognitionRef.current) return
    const recognition = new Ctor()
    recognition.lang = navigator.language || 'en-US'
    recognition.continuous = true
    recognition.interimResults = true
    recognition.onresult = (event) => {
      let finalText = ''
      let interimText = ''
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i]
        if (result.isFinal) finalText += result[0].transcript
        else interimText += result[0].transcript
      }
      if (finalText) onTranscript(finalText, true)
      else if (interimText) onTranscript(interimText, false)
    }
    recognition.onend = () => {
      recognitionRef.current = null
      setListening(false)
    }
    recognition.onerror = () => {
      recognitionRef.current = null
      setListening(false)
    }
    recognitionRef.current = recognition
    recognition.start()
    setListening(true)
  }, [onTranscript])

  useEffect(() => () => recognitionRef.current?.abort(), [])

  return { supported, listening, start, stop }
}

/** Text-to-speech via window.speechSynthesis (cancel-on-new). */
export function useSpeechSynthesis() {
  const supported = speechSynthesisSupported()
  useEffect(() => () => stopSpeaking(), [])
  return { supported, speak, stop: stopSpeaking }
}
