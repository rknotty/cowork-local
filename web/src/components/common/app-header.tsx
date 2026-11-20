import type { ReactElement } from "react";
import sccLogoWhite from "../../assets/scc-logo-white.png";
import { PRODUCT_NAME, PRODUCT_SCOPE } from "../../brand";

/**
 * The SCC header: product name on the left, the SCC logo top-right as the
 * brand's default placement. Always black, so the white logo is used in both
 * themes, as the logo rules require.
 */
export function AppHeader(): ReactElement {
  return (
    <header className="app-header">
      <p>
        <span className="app-header-name">{PRODUCT_NAME}</span>
        <span className="app-header-scope">{PRODUCT_SCOPE}</span>
      </p>
      <img className="app-header-logo" src={sccLogoWhite} alt="SCC" width={81} height={40} />
    </header>
  );
}
