# GTA VI Shorts Automation — starter

## Funciones
- Radar RSS y consulta opcional de YouTube Data API.
- Guion original en inglés.
- Voz Edge TTS.
- Vídeo vertical inicial con tarjeta gráfica original.
- Subida OAuth a YouTube como PRIVADO para revisión.

## Secretos de GitHub
`YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`; opcional `YOUTUBE_API_KEY`.

## Importante
YouTube Data API no revela el volumen exacto de búsquedas. La consulta de búsqueda consume cuota, por eso se hace como máximo una vez por ejecución. GitHub Actions puede retrasar los cron de 15 minutos.
El generador inicial crea una tarjeta gráfica original, NO descarga capturas de GTA VI ni vídeos de terceros. Solo añade material visual externo cuando se compruebe su licencia. No descargues ni reutilices vídeos de la lista NO COPYRIGHT sin verificar la autorización del titular.
La subida queda como privada para revisión. No se activa publicación pública automática por defecto.
Si OAuth está en modo de prueba, los refresh tokens pueden caducar a los 7 días para permisos de YouTube. Revisa Google Auth Platform antes de dejarlo funcionando permanentemente.
