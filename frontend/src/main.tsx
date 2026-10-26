import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './landing.css';

type Feature = { id: string; title: string; body: string; meta: string };
const features: Feature[] = [
  { id: '01', title: 'Code with controls', body: 'Copy and download code blocks. Run HTML in an isolated sandbox preview; other languages need a separate execution runner.', meta: 'COPY · DOWNLOAD · RUN · PREVIEW' },
  { id: '02', title: 'Six focused agents', body: 'Planner, researcher, builder, reviewer, optimizer and tester produce one integrated task result.', meta: 'PLAN → BUILD → REVIEW → TEST' },
  { id: '03', title: 'Free-first routes', body: 'Use provider free tiers and local models when configured. Quotas vary, and a failed selected model is not silently replaced.', meta: 'EXPLICIT MODEL ROUTING' },
  { id: '04', title: 'Session-scoped files', body: 'Upload, inspect, preview and download your work. MP4 branding asset and both logo marks stay included.', meta: 'UPLOAD · PREVIEW · EXPORT' },
  { id: '05', title: 'Server-side protection', body: 'Verified Google sign-in, encrypted HttpOnly sessions, request rate limits, security headers and server-side provider keys.', meta: 'AUTH · ACCESS CONTROL · DIAGNOSTICS' },
  { id: '06', title: 'External gateways', body: 'OmniRoute, New-API and One-API connect through configured OpenAI-compatible endpoints; each remains a separately deployed service.', meta: 'EXPLICIT URL + KEY REQUIRED' }
];

function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => { document.title = 'MAD X — Build Beyond Limits'; }, []);
  return <div className="tsx-page">
    <div className="tsx-aurora" aria-hidden="true" />
    <header className="tsx-nav">
      <a className="tsx-brand" href="/"><span className="tsx-logos"><img src="/static/assets/mad-x-logo.svg" alt="MAD X current logo" /><img src="/static/assets/logo-mark.svg" alt="MAD X original logo" /></span><span><b>MAD<span>X</span></b><small>HYBRID AI STUDIO</small></span></a>
      <button className="tsx-menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(v => !v)}>{menuOpen ? '×' : '☰'}</button>
      <nav className={menuOpen ? 'tsx-links open' : 'tsx-links'}><a href="#features" onClick={() => setMenuOpen(false)}>Features</a><a href="#auth" onClick={() => setMenuOpen(false)}>Security</a><a href="/diagnostics">Diagnostics</a><a className="tsx-cta" href="/chat">Open workspace ↗</a></nav>
    </header>
    <main>
      <section className="tsx-hero">
        <div className="tsx-copy"><div className="tsx-kicker"><i /> FREE-FIRST · SECURE BY DESIGN</div><h1>Build beyond<br /><em>the ordinary.</em></h1><p>One prompt, one selected model, six focused agents when you need them. Ship code, preview HTML, work with files and connect the gateways you operate.</p><div className="tsx-actions"><a className="tsx-primary" href="/chat">Enter MAD X <span>↗</span></a><a className="tsx-secondary" href="#features">Explore features</a></div><div className="tsx-proof"><strong>Keys stay server-side.</strong><small>Verified sign-in · Session-bound files · Real status only</small></div></div>
        <div className="tsx-screen"><div className="tsx-screenbar"><span>● ● ●</span><b>MX / COMMAND CENTER</b><i>LIVE</i></div><div className="tsx-screenbody"><img src="/static/assets/mad-x-icon.png" alt="MAD X icon" /><div><small>YOUR INTELLIGENCE WORKSPACE</small><h2>Make something<br /><em>remarkable.</em></h2><p>Plan clearly. Build safely. See what is connected.</p></div><div className="tsx-snippet"><span>HTML</span><code>&lt;main class="future"&gt;Build it.&lt;/main&gt;</code><a href="/chat">Open editor ↗</a></div></div></div>
      </section>
      <section className="tsx-features" id="features"><div className="tsx-section-title"><small>01 / STUDIO</small><h2>Powerful tools.<br /><em>Transparent status.</em></h2></div><div className="tsx-grid">{features.map(f => <article className="tsx-card" key={f.id}><span>{f.id}</span><h3>{f.title}</h3><p>{f.body}</p><small>{f.meta}</small></article>)}</div></section>
      <section className="tsx-film"><video src="/static/assets/logo-demo.mp4" poster="/static/assets/mad-x-icon.png" muted loop playsInline controls preload="metadata" /><div><small>BRAND FILM / PRESERVED ASSET</small><h2>Both logos.<br /><em>One MAD X.</em></h2><p>The original SVG and the refreshed logo remain in the project.</p></div></section>
      <section className="tsx-auth" id="auth"><div><small>02 / SECURITY</small><h2>TSX is a build format.<br /><em>Not a security boundary.</em></h2><p>Browser source can still be inspected. The protection comes from backend verification, session tokens, scoped file access, rate limiting and keeping provider credentials out of client code.</p></div><a className="tsx-primary" href="/diagnostics">Check connectors ↗</a></section>
    </main>
    <footer className="tsx-footer"><span>MAD<span>X</span> · HYBRID AI STUDIO v17.0.0</span><div><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/chat">Workspace</a></div></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><Landing /></React.StrictMode>);
