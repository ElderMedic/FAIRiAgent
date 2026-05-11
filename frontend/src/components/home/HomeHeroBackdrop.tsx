/**
 * Atmospheric overlay layered on top of the page-level video backdrop while
 * the hero is in view. The video itself lives in `HomePageBackdrop` so that
 * the same footage continues playing as the user scrolls past the fold.
 */
export default function HomeHeroBackdrop() {
  return (
    <div className="home-hero-backdrop" aria-hidden="true">
      <div className="home-hero-backdrop__vignette" />
      <div className="home-hero-backdrop__orb home-hero-backdrop__orb--left" />
      <div className="home-hero-backdrop__orb home-hero-backdrop__orb--right" />
      <div className="home-hero-backdrop__beam" />
      <div className="home-hero-backdrop__halo" />
      <div className="home-hero-backdrop__scanlines" />
    </div>
  );
}
