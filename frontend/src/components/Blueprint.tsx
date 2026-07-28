/**
 * The design system's registration marks.
 *
 * Every `.blueprint` box in the imported design carries four `<i class="corner">`
 * children; this renders that set so screens don't repeat it inline.
 */
export function Corners() {
  return (
    <>
      <i className="corner tl" />
      <i className="corner tr" />
      <i className="corner bl" />
      <i className="corner br" />
    </>
  );
}

/** A meter bar: `.ak-meter` frame with an accent fill, as used for XP and stats. */
export function Meter({ width, small = false }: { width: string; small?: boolean }) {
  return (
    <div className={small ? "ak-meter-sm" : "ak-meter"}>
      <div className="ak-meter-fill" style={{ width }} />
    </div>
  );
}
