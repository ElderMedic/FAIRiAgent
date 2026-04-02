import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import ScrollToTop from './components/ScrollToTop';
import SessionRouteSync from './components/SessionRouteSync';
import Home from './pages/Home';
import Upload from './pages/Upload';
import Config from './pages/Config';
import Run from './pages/Run';
import Result from './pages/Result';
import About from './pages/About';
import Recover from './pages/Recover';
import FairdsStats from './pages/FairdsStats';

export default function App() {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <SessionRouteSync />
      <Layout>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/about" element={<About />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/recover" element={<Recover />} />
          <Route path="/fairds-stats" element={<FairdsStats />} />
          <Route path="/config" element={<Config />} />
          <Route path="/run/:projectId" element={<Run />} />
          <Route path="/result/:projectId" element={<Result />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
