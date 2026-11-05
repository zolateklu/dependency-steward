import { z } from 'zod';

const invitation = z.object({ name: z.string().min(2), email: z.string().email() });

export function validateInvitation(value: unknown): { valid: boolean; messages: string[] } {
  const result = invitation.safeParse(value);
  if (result.success) return { valid: true, messages: [] };
  return { valid: false, messages: result.error.issues.map((issue: z.ZodIssue) => issue.message) };
}
