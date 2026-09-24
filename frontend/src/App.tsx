import { BrowserRouter } from 'react-router-dom';

import { AppRoutes } from './routes/AppRoutes';
import { AuthProvider } from './lib/AuthContext';
import { ThemeProvider } from './theme/ThemeContext';

function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
