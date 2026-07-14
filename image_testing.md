## TEST AGENT PROMPT – IMAGE INTEGRATION RULES ##
Always use base64-encoded images for all tests and requests.
Accepted formats: JPEG, PNG, WEBP only. Every image must contain real
visual features (objects, edges, textures, shadows). Do not use blank
or solid-color images. Re-detect MIME after transcoding. For animated
images extract the first frame only. Resize large images to reasonable
bounds (avoid oversized payloads).
