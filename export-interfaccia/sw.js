/*
  Service worker minimo: solo per soddisfare il requisito di installabilita'
  PWA (un browser non offre "Aggiungi a Home" senza un service worker
  registrato). Nessuna cache offline reale -- Eidos dipende dal cloud per
  tutto (voce, Orchestratore), senza rete non c'e' nulla di utile da servire
  da cache. Vedi docs/modules/08-interfaccia-utente.md, sezione "PWA".
*/
self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', () => {
  // Nessun intercept: tutte le richieste vanno in rete come al solito.
});
