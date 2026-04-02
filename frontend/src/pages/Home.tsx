import { useNavigate } from 'react-router-dom';
import HomeCtaSection from '../components/home/HomeCtaSection';
import HomeHero from '../components/home/HomeHero';
import HomeValueSection from '../components/home/HomeValueSection';
import HomeWorkflowSection from '../components/home/HomeWorkflowSection';
import {
  consoleSlides,
  heroSignals,
  valueCards,
  workflowSteps,
} from '../components/home/content';
import { usePageTitle } from '../hooks/usePageTitle';
import './Home.css';

export default function Home() {
  usePageTitle('Home');
  const navigate = useNavigate();

  return (
    <div className="home-page">
      <HomeHero
        onStart={() => navigate('/upload')}
        onSample={() => navigate('/upload', { state: { demoMode: true } })}
        signals={heroSignals}
        consoleSlides={consoleSlides}
      />
      <HomeValueSection cards={valueCards} />
      <HomeWorkflowSection steps={workflowSteps} />
      <HomeCtaSection
        onStart={() => navigate('/upload')}
        onAbout={() => navigate('/about')}
      />
    </div>
  );
}
