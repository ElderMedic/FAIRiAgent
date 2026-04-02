import heroVideo from '../../assets/home-hero-video.mp4';

export default function HomeHeroBackdrop() {
  return (
    <div className="home-hero-backdrop" aria-hidden="true">
      <video
        className="home-hero-backdrop__video"
        autoPlay
        muted
        loop
        playsInline
        preload="auto"
      >
        <source src={heroVideo} type="video/mp4" />
      </video>
      <div className="home-hero-backdrop__vignette" />
      <div className="home-hero-backdrop__orb home-hero-backdrop__orb--left" />
      <div className="home-hero-backdrop__orb home-hero-backdrop__orb--right" />
      <div className="home-hero-backdrop__beam" />
      <div className="home-hero-backdrop__halo" />
      <div className="home-hero-backdrop__scanlines" />
    </div>
  );
}
