import { useState } from 'react'
import { Button, Group, Text } from '@mantine/core'
import { copyToClipboard } from '../lib/clipboard'

/** A code/copy-button row — copyToClipboard (not Mantine's CopyButton,
 * which has no fallback) so this also works over plain HTTP on a non-
 * localhost origin (e.g. http://pees:8000), where navigator.clipboard is
 * present but silently refuses to write — found by direct testing. Shared
 * by AgentsPage (install/token) and AgentDetailPage (upgrade command). */
export default function CopyField({ value, mono = true }: { value: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false)
  return (
    <Group wrap="nowrap" gap="xs" align="flex-start">
      <Text
        component={mono ? 'code' : 'span'}
        style={{ flex: 1, wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}
        bg="var(--mantine-color-default-hover)"
        p="xs"
        fz="sm"
      >
        {value}
      </Text>
      <Button
        size="xs"
        color={copied ? 'teal' : 'flame'}
        onClick={async () => {
          const ok = await copyToClipboard(value)
          setCopied(ok)
          if (ok) setTimeout(() => setCopied(false), 2000)
        }}
      >
        {copied ? 'Copied' : 'Copy'}
      </Button>
    </Group>
  )
}
