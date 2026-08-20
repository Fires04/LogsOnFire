/** navigator.clipboard.writeText() requires a "secure context" (HTTPS or
 * localhost) — on a plain-HTTP LAN deployment of this self-hosted tool
 * (e.g. http://pees:8000, no reverse proxy/TLS) the API object is present
 * but every call silently rejects, which Mantine's CopyButton/useClipboard
 * has no fallback for (found by direct testing: the button just did
 * nothing, no error surfaced anywhere). Fall back to the legacy
 * execCommand('copy') via a hidden textarea, which still works over plain
 * HTTP in every browser that matters here.
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the legacy path below
    }
  }
  try {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    textarea.style.pointerEvents = 'none'
    document.body.appendChild(textarea)
    textarea.focus()
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}
