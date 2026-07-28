/*
  AudioWorkletProcessor che cattura il microfono in pezzi grezzi Float32 (un
  blocco Web Audio, 128 campioni) e li spedisce al thread principale via
  port.postMessage -- ne' bloccante ne' throttled dal thread UI, a differenza
  di un vecchio ScriptProcessorNode. Il thread principale (app.js) li converte
  in PCM 16 bit, li accoda per il pre-roll o li spedisce, e ne calcola il
  livello (RMS) per il cancello VAD e il pilotaggio dell'Essere Vivente --
  vedi docs/modules/08-interfaccia-utente.md "Ascolto continuo e attivazione
  col nome".
*/
class PCMCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (channel && channel.length) {
      // slice(): il buffer di 'channel' e' riusato dal motore audio al blocco
      // successivo, va copiato prima di attraversare il postMessage.
      this.port.postMessage(channel.slice());
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCaptureProcessor);
