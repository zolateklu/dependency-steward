import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { validateInvitation } from './schema';

function App() {
  const [message, setMessage] = useState('Invite a teammate to your workspace.');
  return <main><h1>Northstar</h1><p>Team workspace</p><form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); const result = validateInvitation(Object.fromEntries(data)); setMessage(result.valid ? 'Invitation is ready.' : result.messages.join(' · ')); }}><label>Name <input name="name"/></label><label>Email <input name="email"/></label><button>Check invitation</button></form><p role="status">{message}</p></main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
