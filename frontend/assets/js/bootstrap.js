// Production uses the Netlify /api proxy; local FastAPI serves the same paths.
window.API_BASE_URL = '';
window.LOGIN_URL = '/home';
window.PLANNER_URL = '/';
window.calendarNow = function(){
  const zone = typeof currentUser !== 'undefined' && currentUser ? currentUser.timezone : undefined;
  return zone ? new Date(new Date().toLocaleString('en-US',{timeZone:zone})) : new Date();
};
