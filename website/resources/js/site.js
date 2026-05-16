window.toggleMenu = function toggleMenu() {
  const navbar = document.getElementById("myNavbar");
  if (!navbar) {
    return;
  }
  navbar.className = navbar.className === "navbar" ? "navbar responsive" : "navbar";
};