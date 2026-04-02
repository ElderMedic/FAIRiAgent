import { Link } from 'react-router-dom';
import { Code2, BookOpen, ExternalLink } from 'lucide-react';
import {
  DEEPWIKI_URL,
  FAIR_DS_URL,
  GITHUB_DOCS_TREE_URL,
  GITHUB_REPO_URL,
} from '../constants/site';
import './site-shell.css';

export default function Footer() {
  const year = new Date().getFullYear();

  return (
    <footer className="site-footer">
      <div className="site-footer__inner">
        <div className="site-footer__grid">
          <div className="site-footer__copy">
            <p className="site-footer__brand">FAIRiAgent</p>
            <p className="site-footer__body">
              Research software for automated FAIR metadata generation. This interface is intended for
              local or trusted-network use. Model outputs may be incomplete or incorrect — always review
              results before publication or compliance decisions.
            </p>
            <p className="site-footer__body site-footer__body--muted">
              Third-party LLM providers and services are subject to their own terms, privacy policies, and
              data handling practices. You are responsible for API keys and for complying with applicable
              policies at your institution.
            </p>
          </div>

          <nav className="site-footer__links" aria-label="Footer links">
            <Link
              to="/about"
              className="site-footer__link site-footer__link--strong"
            >
              About
            </Link>
            <a
              href={GITHUB_REPO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="site-footer__link"
            >
              <Code2 className="site-footer__icon" aria-hidden />
              GitHub repository
              <ExternalLink className="site-footer__icon site-footer__icon--small" aria-hidden />
            </a>
            <a
              href={GITHUB_DOCS_TREE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="site-footer__link"
            >
              <BookOpen className="site-footer__icon" aria-hidden />
              Documentation (docs/)
              <ExternalLink className="site-footer__icon site-footer__icon--small" aria-hidden />
            </a>
            <a
              href={FAIR_DS_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="site-footer__link"
            >
              FAIR Data Station
            </a>
            <a
              href={DEEPWIKI_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="site-footer__link"
            >
              DeepWiki
            </a>
          </nav>
        </div>

        <div className="site-footer__bottom">
          <p>
            © {year} FAIRiAgent contributors. Open-source under the project license — see the repository
            for details.
          </p>
        </div>
      </div>
    </footer>
  );
}
