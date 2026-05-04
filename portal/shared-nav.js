// Shared navigation for all Command Center pages
(function(){
  // Inject nav CSS if not already present
  if(!document.getElementById('shared-nav-css')){
    const s=document.createElement('style');
    s.id='shared-nav-css';
    s.textContent=`.nav{background:rgba(255,255,255,.72);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);border-bottom:1px solid rgba(0,0,0,.06);padding:12px 24px;display:flex;align-items:center;gap:24px;position:sticky;top:0;z-index:10}.nav a{text-decoration:none;color:#86868b;font-size:14px;transition:color .2s}.nav a:hover{color:#0071e3}.nav-brand{font-weight:700;color:#1d1d1f!important;font-size:15px!important}.nav-active{color:#0071e3!important;font-weight:600}[data-theme="dark"] .nav-active{color:#f59e0b!important}[data-theme="dark"] .nav{background:rgba(10,10,15,.85);border-bottom-color:#1e293b}[data-theme="dark"] .nav a{color:#94a3b8}[data-theme="dark"] .nav a:hover{color:#f59e0b}[data-theme="dark"] .nav-brand{color:#e2e8f0!important}.nav-inner{display:flex;align-items:center;gap:24px;max-width:1100px;margin:0 auto;width:100%}.theme-toggle{background:none;border:1px solid rgba(0,0,0,.12);border-radius:8px;padding:4px 12px;cursor:pointer;font-size:14px;color:#86868b;margin-left:auto}[data-theme="dark"] .theme-toggle{border-color:#334155;color:#94a3b8}.nav-hamburger{display:none;background:none;border:none;font-size:20px;cursor:pointer;color:#86868b;padding:4px 8px}@media(max-width:640px){.nav{padding:10px 16px}.nav-inner{gap:0;flex-wrap:wrap}.nav-inner .nav-link{display:none}.nav-inner.open .nav-link{display:block;width:100%;padding:8px 0;border-bottom:1px solid rgba(0,0,0,.06)}.nav-hamburger{display:block;margin-left:auto}[data-theme="dark"] .nav-inner .nav-link{border-bottom-color:#1e293b}}`;
    document.head.appendChild(s);
  }
  const pages=[
    {href:'/portal',label:'\u26a1 Command Center',brand:true},
    {href:'/portal#quick',label:'\u5feb\u901f\u8bbf\u95ee'},
    {href:'/docs',label:'\ud83d\udcda \u6587\u6863'},
    {href:'/knowledge',label:'\ud83e\udde0 \u77e5\u8bc6\u5e93'},
    {href:'/usage',label:'\ud83d\udcca \u7528\u91cf'},
  ];
  const cur=location.pathname.replace(/\/$/,'');
  // Remove existing nav if any (to avoid duplicates)
  const old=document.querySelector('.nav');
  if(old)old.remove();
  const nav=document.createElement('nav');
  nav.className='nav';
  const inner=document.createElement('div');
  inner.className='nav-inner';
  pages.forEach(p=>{
    const a=document.createElement('a');
    a.href=p.href;
    a.textContent=p.label;
    a.className=p.brand?'nav-brand':'nav-link';
    const match=p.href.replace(/\/$/,'');
    if(cur===match&&!p.brand)a.classList.add('nav-active');
    inner.appendChild(a);
  });
  const btn=document.createElement('button');
  btn.className='theme-toggle';
  btn.textContent='\ud83c\udf13';
  btn.onclick=function(){
    const d=document.documentElement;
    const isDark=d.getAttribute('data-theme')==='dark';
    d.setAttribute('data-theme',isDark?'light':'dark');
    localStorage.setItem('cc_theme',isDark?'light':'dark');
  };
  const burger=document.createElement('button');
  burger.className='nav-hamburger';
  burger.textContent='\u2630';
  burger.onclick=function(){inner.classList.toggle('open')};
  inner.appendChild(burger);
  inner.appendChild(btn);
  nav.appendChild(inner);
  document.body.insertBefore(nav,document.body.firstChild);
  const t=localStorage.getItem('cc_theme');
  if(t==='dark'||(!t&&window.matchMedia('(prefers-color-scheme:dark)').matches)){
    document.documentElement.setAttribute('data-theme','dark');
  }
})();
