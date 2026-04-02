import type { ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { Dna } from 'lucide-react';
import Footer from './Footer';
import './site-shell.css';

interface LayoutProps {
  children: ReactNode;
}

const navLinks = [
  { path: '/', label: 'Home' },
  { path: '/upload', label: 'Upload' },
  { path: '/fairds-stats', label: 'FAIR-DS Stats' },
  { path: '/recover', label: 'Recover' },
  { path: '/about', label: 'About' },
];

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const isHome = location.pathname === '/';

  return (
    <div className={`site-shell ${isHome ? 'site-shell--home' : ''}`}>
      <a
        href="#main-content"
        className="site-shell__skip"
      >
        Skip to main content
      </a>
      <nav className="site-nav-wrap" aria-label="Primary navigation">
        <div className={`site-nav ${isHome ? 'site-nav--home' : 'site-nav--default'}`}>
          <Link to="/" className="site-brand">
            <Dna className="site-brand__icon" aria-hidden="true" />
            <span className="site-brand__label">FAIRiAgent</span>
          </Link>

          <div className="site-nav__links">
            {navLinks.map((link) => (
              <NavLink
                key={link.path}
                to={link.path}
                end={link.path === '/'}
                className={({ isActive }) =>
                  [
                    'site-nav__link',
                    isHome ? 'site-nav__link--home' : 'site-nav__link--default',
                    isActive ? 'is-active' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')
                }
              >
                {link.label}
              </NavLink>
            ))}
          </div>
        </div>
      </nav>

      <main id="main-content" className="site-shell__main" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </div>
  );
}
