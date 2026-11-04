import { describe, expect, it } from 'vitest';
import { validateInvitation } from './schema';

describe('Team invitations', () => {
  it('accepts a valid invitation', () => expect(validateInvitation({name: 'Ada', email: 'ada@example.com'})).toEqual({valid: true, messages: []}));
  it('rejects invalid emails with a message', () => { const result = validateInvitation({name: 'Ada', email: 'invalid'}); expect(result.valid).toBe(false); expect(result.messages).toHaveLength(1); });
  it('rejects missing names', () => expect(validateInvitation({email: 'ada@example.com'}).valid).toBe(false));
  it('reports both invalid fields', () => expect(validateInvitation({name: '', email: ''}).messages).toHaveLength(2));
});
